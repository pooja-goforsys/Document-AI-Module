"""
Multi-backend cross-encoder reranker — second-pass retrieval quality filter.

Priority order (backend="auto"):  cohere → jina → local_bge → local_ms_marco

Local model options (backend="local"):
  BAAI/bge-reranker-v2-m3           (default) — 568 M params; excellent on
                                     enterprise policy / HR / technical docs.
                                     Distinguishes within-domain subtopics
                                     (VPN policy vs Travel policy) far better
                                     than the ms-marco web-search model.
  cross-encoder/ms-marco-MiniLM-L-6-v2 — 22 M params; faster; weaker on
                                     within-domain distinction.

API options (no model download required):
  Cohere Rerank v3  — set COHERE_API_KEY in backend/.env
  Jina Reranker     — set JINA_API_KEY   in backend/.env

Pipeline:
  1. Bi-encoder vector + keyword search → top-20 candidates
  2. Cross-encoder rerank               → score each (question, chunk) pair
  3. Score-gap pruning                  → cut at the first large score cliff
  4. Threshold filter                   → discard chunks below RERANKER_MIN_SCORE
  5. Minimum-results guarantee          → top-up to RERANKER_MIN_RESULTS if needed
  6. Return top-K                       → send to LLM

Score semantics after sigmoid normalisation (local models):
  0.00 – 0.29  very unlikely to answer the question
  0.30 – 0.49  borderline — may contain partial information
  0.50 – 0.74  likely relevant
  0.75 – 1.00  highly relevant, directly answers
"""
import asyncio
import logging
import math
import platform
import sys
from typing import Any

logger = logging.getLogger(__name__)

# ── Local model state ─────────────────────────────────────────────────────────
_model: Any = None
_model_name_loaded: str = ""
_model_failed: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sigmoid(x: float) -> float:
    x = max(-30.0, min(30.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _load_local_model(model_id: str) -> Any:
    """Lazy-load a local cross-encoder model.  Returns None on permanent failure."""
    global _model, _model_name_loaded, _model_failed

    if (
        model_id == "BAAI/bge-reranker-v2-m3"
        and platform.system().lower() == "windows"
        and sys.version_info >= (3, 14)
    ):
        logger.warning(
            "[Reranker] Skipping BAAI/bge-reranker-v2-m3 on Windows/Python 3.14. "
            "This model can terminate the Python process during load in this environment. "
            "Using bi-encoder order for this request. Set RERANKER_MODEL="
            "cross-encoder/ms-marco-MiniLM-L-6-v2 for local reranking."
        )
        _model_failed = True
        return None

    if _model_failed:
        return None
    if _model is not None and _model_name_loaded == model_id:
        return _model

    try:
        from sentence_transformers.cross_encoder import CrossEncoder
        try:
            _model = CrossEncoder(model_id)
        except Exception as first_exc:
            logger.warning(
                f"[Reranker] Online load failed ({first_exc!r}), "
                "retrying from local cache (local_files_only=True)"
            )
            _model = CrossEncoder(model_id, local_files_only=True)
        _model_name_loaded = model_id
        logger.info(f"[Reranker] Loaded local model: {model_id}")
        return _model
    except Exception as exc:
        logger.warning(
            f"[Reranker] Could not load local model {model_id!r} ({exc!r}). "
            "Falling back to bi-encoder ranking."
        )
        _model_failed = True
        return None


# ── Scoring backends ──────────────────────────────────────────────────────────

def _score_local(
    model: Any,
    question: str,
    candidates: list[tuple],
) -> list[float]:
    """Score with a local cross-encoder.  Returns sigmoid-normalized scores."""
    pairs = [
        (question, (chunk.content or "")[:512])
        for chunk, _doc, _dist in candidates
    ]
    raw = model.predict(pairs)
    return [_sigmoid(float(s)) for s in raw]


async def _score_cohere(
    question: str,
    candidates: list[tuple],
    api_key: str,
    model: str = "rerank-english-v3.0",
) -> list[float] | None:
    """
    Score with Cohere Rerank v3 API.

    Returns a list of relevance scores (0-1) in candidate order,
    or None on any error (caller falls back to local).
    """
    try:
        import cohere
        co = cohere.AsyncClient(api_key=api_key)
        docs = [(chunk.content or "")[:512] for chunk, _, _ in candidates]
        response = await co.rerank(
            query=question,
            documents=docs,
            model=model,
            top_n=len(docs),
        )
        # Cohere returns results sorted by relevance_score; we need them in input order
        score_map: dict[int, float] = {
            r.index: r.relevance_score for r in response.results
        }
        scores = [score_map.get(i, 0.0) for i in range(len(docs))]
        logger.info(
            f"[Reranker] Cohere scored {len(docs)} candidates  "
            f"model={model}  best={max(scores):.4f}"
        )
        return scores
    except ImportError:
        logger.warning(
            "[Reranker] 'cohere' package not installed. "
            "Run: pip install cohere  OR  set RERANKER_BACKEND=local"
        )
        return None
    except Exception as exc:
        logger.warning(f"[Reranker] Cohere API error: {exc}")
        return None


async def _score_jina(
    question: str,
    candidates: list[tuple],
    api_key: str,
    model: str = "jina-reranker-v2-base-multilingual",
) -> list[float] | None:
    """
    Score with Jina Reranker API.

    Returns relevance scores (0-1) in candidate order, or None on error.
    """
    try:
        import httpx
        docs = [{"text": (chunk.content or "")[:512]} for chunk, _, _ in candidates]
        payload = {
            "model":     model,
            "query":     question,
            "documents": docs,
            "top_n":     len(docs),
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.jina.ai/v1/rerank",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        score_map: dict[int, float] = {
            r["index"]: r["relevance_score"] for r in results
        }
        scores = [score_map.get(i, 0.0) for i in range(len(docs))]
        logger.info(
            f"[Reranker] Jina scored {len(docs)} candidates  "
            f"model={model}  best={max(scores):.4f}"
        )
        return scores
    except Exception as exc:
        logger.warning(f"[Reranker] Jina API error: {exc}")
        return None


# ── Score-gap pruning ─────────────────────────────────────────────────────────

def _prune_score_gap(
    paired: list[tuple[float, tuple]],
    gap_threshold: float,
    min_results: int,
) -> list[tuple[float, tuple]]:
    """
    Cut the ranked list at the first large score drop.

    Example:
      VPN chunk:     0.78
      VPN detail:    0.71    gap = 0.07  < threshold → keep
      Travel:        0.22    gap = 0.49  ≥ threshold → CUT HERE
      PTO:           0.18
      Approvals:     0.14

    Result: only VPN chunk + VPN detail returned.

    The cut is never applied if it would leave fewer than min_results chunks.
    """
    if len(paired) <= 1 or gap_threshold <= 0:
        return paired

    for i in range(1, len(paired)):
        gap = paired[i - 1][0] - paired[i][0]
        if gap >= gap_threshold:
            pruned = paired[:i]
            if len(pruned) >= min_results:
                logger.info(
                    f"[Reranker] Score-gap prune: cut at index {i}  "
                    f"gap={gap:.4f}  "
                    f"kept={len(pruned)}  "
                    f"removed={len(paired) - len(pruned)}  "
                    f"scores_kept={[round(s, 4) for s, _ in pruned]}"
                )
                return pruned
            else:
                logger.info(
                    f"[Reranker] Score-gap prune: gap={gap:.4f} at index {i} "
                    f"would leave {len(paired[:i])} < min_results={min_results} — skipping cut"
                )
                break

    return paired


# ── Public API ────────────────────────────────────────────────────────────────

async def rerank(
    question: str,
    candidates: list[tuple],
    top_k: int,
    min_score: float,
    min_results: int = 2,
) -> list[tuple]:
    """
    Rerank (DocumentChunk, Document, dist) triples.

    Backend selection:
      settings.RERANKER_BACKEND = "local"  → local cross-encoder model
      settings.RERANKER_BACKEND = "cohere" → Cohere Rerank v3 API
      settings.RERANKER_BACKEND = "jina"   → Jina Reranker API
      settings.RERANKER_BACKEND = "auto"   → cohere → jina → local (first available)

    Returns (chunk, doc, 1-score) sorted best-first.
    Falls back to bi-encoder order on any unrecoverable error.
    """
    if not candidates:
        return []

    from app.core.config import settings

    loop   = asyncio.get_running_loop()
    scores: list[float] | None = None
    backend_used = "bi-encoder_fallback"

    # ── Backend selection ─────────────────────────────────────────────────────
    backend = (settings.RERANKER_BACKEND or "local").lower()

    # Cohere
    if backend in ("cohere", "auto") and (settings.COHERE_API_KEY or "").strip():
        scores = await _score_cohere(
            question, candidates, settings.COHERE_API_KEY.strip()
        )
        if scores is not None:
            backend_used = "cohere"

    # Jina
    if scores is None and backend in ("jina", "auto") and (settings.JINA_API_KEY or "").strip():
        scores = await _score_jina(
            question, candidates, settings.JINA_API_KEY.strip()
        )
        if scores is not None:
            backend_used = "jina"

    # Local cross-encoder
    if scores is None and backend in ("local", "auto"):
        model = _load_local_model(settings.RERANKER_MODEL)
        if model is not None:
            try:
                scores = await loop.run_in_executor(
                    None, lambda: _score_local(model, question, candidates)
                )
                backend_used = f"local:{settings.RERANKER_MODEL}"
            except Exception as exc:
                logger.warning(
                    f"[Reranker] Local model inference failed: {exc} — using bi-encoder order"
                )

    # ── Fallback — no backend succeeded ──────────────────────────────────────
    if scores is None:
        logger.warning(
            "[Reranker] All backends failed or unavailable — using bi-encoder order. "
            "Set RERANKER_BACKEND=local and ensure sentence-transformers is installed, "
            "OR set COHERE_API_KEY / JINA_API_KEY in backend/.env."
        )
        return candidates[:top_k]

    # ── Sort ──────────────────────────────────────────────────────────────────
    paired = sorted(
        zip(scores, candidates), key=lambda x: x[0], reverse=True
    )

    # ── Debug log ─────────────────────────────────────────────────────────────
    logger.info(
        f"[Reranker] Scores — backend={backend_used}  question={question[:80]!r}"
    )
    for rank, (score, (chunk, doc, dist)) in enumerate(paired[:15], 1):
        be_sim  = round(1.0 - float(dist), 4)
        preview = (chunk.content or "").replace("\n", " ")[:80]
        tier    = "HIGH" if score >= 0.65 else "MED" if score >= 0.30 else "LOW"
        logger.info(
            f"[Reranker]  [{rank:2d}] ce={score:.4f} [{tier}]  "
            f"be={be_sim:.4f}  "
            f"doc={doc.original_name!r:35s}  "
            f"page={str(chunk.page_number):>4}  "
            f"preview={preview!r}"
        )

    # ── Score-gap pruning ─────────────────────────────────────────────────────
    if settings.RERANKER_SCORE_GAP_PRUNE:
        paired = _prune_score_gap(
            paired, settings.RERANKER_SCORE_GAP_THRESHOLD, min_results
        )

    # ── Threshold filter ──────────────────────────────────────────────────────
    above = [(s, t) for s, t in paired if s >= min_score]
    below = [(s, t) for s, t in paired if s < min_score]

    kept = list(above)

    # Top-up to min_results from below-threshold candidates only if needed
    if len(kept) < min_results and below:
        needed   = min_results - len(kept)
        fallback = below[:needed]
        kept.extend(fallback)
        kept.sort(key=lambda x: x[0], reverse=True)
        logger.info(
            f"[Reranker] Below-threshold top-up: +{len(fallback)} chunk(s) "
            f"(scores {[round(s,3) for s,_ in fallback]}) to meet min_results={min_results}"
        )

    if not kept:
        logger.warning("[Reranker] No scored candidates — returning bi-encoder order")
        return candidates[:top_k]

    # ── Build result ──────────────────────────────────────────────────────────
    # Replace cosine dist with (1 - ce_score) so all downstream code
    # (_format_context, _calculate_confidence, confidence gate) sees the
    # cross-encoder relevance rather than bi-encoder similarity.
    result = [
        (chunk, doc, round(1.0 - ce_score, 6))
        for ce_score, (chunk, doc, _old_dist) in kept[:top_k]
    ]

    above_cnt = min(len(above), top_k)
    below_cnt = len(result) - above_cnt
    logger.info(
        f"[Reranker] {len(candidates)} candidates → {len(result)} returned  "
        f"backend={backend_used}  "
        f"above_threshold={above_cnt}  "
        f"fallback_below={below_cnt}  "
        f"min_score={min_score:.2f}  "
        f"top_k={top_k}  "
        f"gap_prune={'on' if settings.RERANKER_SCORE_GAP_PRUNE else 'off'}"
    )
    return result
