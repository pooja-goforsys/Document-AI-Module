"""
Background indexing task — robust pipeline with quality validation.

Pipeline:
  1. Mark document as 'indexing'
  2. Parse file → ParsedChunk list  (thread executor — non-blocking)
  3. Embed chunks in batches         (thread executor — non-blocking, with retry)
  4. Bulk-insert DocumentChunk rows  (flushed in batches)
  5. Mark document as 'indexed'
  6. Generate AI summary             (non-fatal, separate session)
  7. Domain classification           (non-fatal, separate session)

Every exception at any step is caught and results in status='failed'.
The document can NEVER be left permanently in 'pending' or 'indexing'.
"""
import asyncio
import re
import time
import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import update
from app.core.database import AsyncSessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.parsers import get_parser
from app.embedders import get_embedder, get_embedding_identity
from app.services.retrieval_metadata import infer_chunk_category

logger = logging.getLogger(__name__)

# ── Tuneable constants ────────────────────────────────────────────────────────
# 30 min — allows 50MB+ PDFs (PyMuPDF is fast, but pypdf fallback can take
# 5-10 min; embedding 1000+ chunks on CPU adds another 2-5 min).
INDEXING_TIMEOUT_SECONDS = 1800

# Texts sent to the embedder per executor call.  64 is the sweet spot:
# large enough to keep the model GPU/CPU saturated, small enough to avoid
# memory spikes on machines with limited RAM.
EMBED_BATCH_SIZE  = 64

# ORM objects flushed per DB round-trip.  100 rows × ~3KB each ≈ 300KB per
# flush — well within asyncpg's default message size limit.
INSERT_BATCH_SIZE = 100

# Embedding retry settings (transient API / model errors)
_MAX_EMBED_RETRIES    = 3
_EMBED_RETRY_BASE_SEC = 2.0   # doubles each attempt: 2s → 4s → give up

# CPU semaphore — limits concurrent parse+embed tasks to 2.
# Without this, uploading 5 large PDFs simultaneously runs 5 SentenceTransformer
# encode() calls in parallel, causing GIL contention and making ALL of them take
# N× longer than a sequential run would.  2 concurrent tasks is a good balance:
# the second upload doesn't wait long, and neither starves the other.
_CPU_SEMAPHORE = asyncio.Semaphore(2)


# ── Public entry point ────────────────────────────────────────────────────────

async def run_indexing_task(
    document_id: uuid.UUID,
    file_path: str,
    file_type: str,
    user_id: uuid.UUID | None = None,
) -> None:
    """
    Safe wrapper around _run_indexing_core.

    Guarantees that the document ends in 'indexed' or 'failed' —
    never in 'pending' or 'indexing' — regardless of what goes wrong.
    """
    logger.info(
        f"[UPLOAD COMPLETE] doc={document_id} type={file_type} "
        f"path={file_path}"
    )
    try:
        await asyncio.wait_for(
            _run_indexing_core(document_id, file_path, file_type, user_id),
            timeout=INDEXING_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        # Server is shutting down — asyncio cancelled this background task.
        # Do NOT write to DB: the event loop / DB pool may already be torn down.
        # Do NOT re-raise: this is the BackgroundTask root; re-raising causes
        # Starlette to log a spurious "Exception in ASGI application".
        # Document stays in 'indexing'; startup recovery re-queues it.
        logger.warning(
            f"[INDEXING CANCELLED] doc={document_id} — server shutdown mid-index; "
            "will be re-queued on next startup"
        )
    except asyncio.TimeoutError:
        msg = (
            f"Indexing timed out after {INDEXING_TIMEOUT_SECONDS}s. "
            "The file may be extremely large or contain unusually complex content."
        )
        logger.error(f"[INDEXING TIMEOUT] doc={document_id} — {msg}")
        await _mark_failed(document_id, msg)
    except Exception as exc:
        # Catches anything that escapes _run_indexing_core (e.g. DB pool
        # exhausted before the inner try/except runs).
        msg = f"Unexpected error: {exc}"
        logger.error(f"[INDEXING CRASH] doc={document_id} — {msg}", exc_info=True)
        await _mark_failed(document_id, str(exc)[:1000])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _mark_failed(document_id: uuid.UUID, reason: str) -> None:
    """Best-effort status → failed.  Never raises."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.failed, error_message=reason[:1000])
            )
            await db.commit()
        logger.info(f"[INDEXING FAILED] doc={document_id} marked failed: {reason[:120]}")
    except Exception as e:
        logger.error(
            f"[INDEXING FAILED] doc={document_id} — could not write failed status: {e}"
        )


async def _safe_notify(
    user_id: uuid.UUID | None,
    title: str,
    message: str,
    ntype: str = "document",
) -> None:
    """Fire-and-forget notification.  Never raises."""
    if user_id is None:
        return
    try:
        from app.services.notification_service import create_notification
        await create_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=ntype,
            db=None,
        )
    except Exception as exc:
        logger.warning(f"[Notification] non-fatal failure: {exc}")


async def _get_doc_name(document_id: uuid.UUID) -> str:
    """Look up original_name once for notification messages."""
    try:
        async with AsyncSessionLocal() as tmp:
            doc = await tmp.get(Document, document_id)
            if doc:
                return doc.original_name
    except Exception:
        pass
    return str(document_id)


async def _embed_with_retry(
    embedder,
    texts: list[str],
    document_id: uuid.UUID,
    batch_start: int,
) -> list[list[float]]:
    """
    Embed a batch of texts with exponential-backoff retry.

    CancelledError is never swallowed — it must propagate so that
    asyncio.wait_for's timeout mechanism works correctly.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_EMBED_RETRIES):
        try:
            return await embedder.embed_texts(texts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_EMBED_RETRIES - 1:
                delay = _EMBED_RETRY_BASE_SEC * (2 ** attempt)
                logger.warning(
                    f"[EMBEDDING RETRY] doc={document_id} "
                    f"batch_start={batch_start} attempt={attempt + 1}/{_MAX_EMBED_RETRIES} "
                    f"error={exc!r} — retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ── Document quality validation ───────────────────────────────────────────────

_CONTAMINATION_PATTERNS: list[tuple] = [
    (
        re.compile(r'\bphase\s+[3-9]\s+(?:test|eval|result|assessment|retrieval)', re.I),
        "evaluation phase content",
    ),
    (
        re.compile(r'\b(?:score\s+table|evaluation\s+(?:result|table|score|report))', re.I),
        "evaluation score table",
    ),
    (
        re.compile(r'\bbenchmark\s+(?:output|result|score|test|data)', re.I),
        "benchmark output",
    ),
    (
        re.compile(r'\btest\s+artifact\b', re.I),
        "test artifact marker",
    ),
    (
        re.compile(r'\bacceptance\s+criteria\b', re.I),
        "acceptance criteria content",
    ),
    (
        re.compile(r'\brag\s+(?:test|eval|pipeline|quality)\b', re.I),
        "RAG evaluation content",
    ),
    (
        re.compile(r'\b(?:precision|recall|f1[\s_]score|mrr|ndcg)\s*(?:@|:|=|\d)', re.I),
        "ML evaluation metrics",
    ),
]


def _validate_document_quality(chunks: list, doc_name: str) -> list[str]:
    """
    Scan extracted chunks for evaluation/test-artifact content that would
    pollute embeddings and degrade retrieval quality.

    This is non-fatal and informational only — indexing proceeds regardless.
    Returns a list of warning strings (empty if the document looks clean).
    """
    from app.core.config import settings
    if not settings.CHUNK_CONTAMINATION_CHECK or not chunks:
        return []

    contaminated: list[str] = []

    for chunk in chunks:
        text = chunk.text or ''
        for pattern, label in _CONTAMINATION_PATTERNS:
            if pattern.search(text):
                if len(contaminated) < 5:
                    contaminated.append(
                        f"page={chunk.page_number} idx={chunk.chunk_index}: {label}"
                    )
                break

    if contaminated:
        pct = round(100 * len(contaminated) / len(chunks), 1)
        summary = (
            f"[DocValidation] '{doc_name}': {len(contaminated)}/{len(chunks)} chunks "
            f"({pct}%) may contain evaluation/test-artifact content — "
            "retrieval quality may be reduced. Re-upload a clean source document."
        )
        logger.warning(summary)
        for detail in contaminated:
            logger.warning(f"[DocValidation]   {detail}")
        return [summary] + contaminated

    logger.info(f"[DocValidation] '{doc_name}': no contamination detected")
    return []


# ── Core pipeline ─────────────────────────────────────────────────────────────

async def _run_indexing_core(
    document_id: uuid.UUID,
    file_path: str,
    file_type: str,
    user_id: uuid.UUID | None = None,
) -> None:
    doc_name  = await _get_doc_name(document_id)
    chunks    = []          # defined here so steps 6/7 always see the variable
    t_total   = time.perf_counter()

    async with AsyncSessionLocal() as db:
        try:
            # ── Step 1: Mark as indexing ──────────────────────────────────────
            logger.info(f"[INDEXING START] doc={document_id} name={doc_name!r}")
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.indexing, error_message=None)
            )
            await db.commit()
            await _safe_notify(user_id, "Indexing started",
                               f"'{doc_name}' is being processed.")

            # ── Steps 2-3: Parse + Embed (CPU-heavy; semaphore-limited) ─────────
            # _CPU_SEMAPHORE ensures at most 2 documents run these stages
            # concurrently, preventing GIL/CPU starvation when many files are
            # uploaded at once.  DB steps (1, 4, 5) are NOT inside the semaphore
            # so they can proceed in parallel.
            async with _CPU_SEMAPHORE:

                # ── Step 2: Parse (thread executor — never blocks event loop) ─
                logger.info(f"[TEXT EXTRACTION START] doc={document_id}")
                t_parse   = time.perf_counter()
                loop      = asyncio.get_running_loop()
                parser    = get_parser(file_type)
                chunks    = await loop.run_in_executor(
                    None,
                    parser.extract_chunks,
                    file_path,
                )
                parse_ms  = (time.perf_counter() - t_parse) * 1000

                if not chunks:
                    raise ValueError(
                        "No text could be extracted from the document. "
                        "The file may be empty, password-protected, or a scanned image."
                    )

                page_count = max(
                    (c.page_number for c in chunks if c.page_number),
                    default=None,
                )
                logger.info(
                    f"[TEXT EXTRACTION COMPLETE] doc={document_id} "
                    f"chunks={len(chunks)} pages={page_count} ({parse_ms:.0f}ms)"
                )

                # ── Detailed extraction logging ───────────────────────────────
                # Chunk size distribution
                sizes = [len(c.text) for c in chunks]
                logger.info(
                    f"[CHUNK STATS] doc={document_id}  "
                    f"total={len(chunks)}  "
                    f"min_chars={min(sizes)}  max_chars={max(sizes)}  "
                    f"avg_chars={sum(sizes)//len(sizes)}"
                )

                # Page → chunk distribution (first 15 pages)
                from collections import Counter as _Counter
                page_dist = _Counter(c.page_number for c in chunks)
                top_pages = sorted(page_dist.items())[:15]
                logger.info(
                    f"[PAGE DIST] doc={document_id}  "
                    f"unique_pages={len(page_dist)}  "
                    f"distribution={top_pages}"
                )

                # First 3 chunk previews (verify extraction is correct)
                for _i, _c in enumerate(chunks[:3], 1):
                    logger.info(
                        f"[CHUNK SAMPLE {_i}] doc={document_id}  "
                        f"page={_c.page_number}  idx={_c.chunk_index}  "
                        f"len={len(_c.text)}  "
                        f"text={_c.text[:200]!r}"
                    )

                # ── Document quality validation ───────────────────────────
                _quality_issues = _validate_document_quality(chunks, doc_name)
                if _quality_issues:
                    # Log headings of contaminated chunks for easy diagnosis
                    _cont_headings = {
                        c.section_heading for c in chunks
                        if c.section_heading and any(
                            pat.search(c.text or '') for pat, _ in _CONTAMINATION_PATTERNS
                        )
                    }
                    if _cont_headings:
                        logger.warning(
                            f"[DocValidation] Affected sections: "
                            f"{list(_cont_headings)[:10]}"
                        )

                # CEO / leadership text detection (answer presence check)
                _ceo_terms = [
                    "chief executive", "ceo", "chairman",
                    "satya", "nadella", "president",
                ]
                _ceo_chunks = [
                    _c for _c in chunks
                    if any(_t in _c.text.lower() for _t in _ceo_terms)
                ]
                if _ceo_chunks:
                    logger.info(
                        f"[CEO DETECT] doc={document_id}  "
                        f"found in {len(_ceo_chunks)} chunk(s)"
                    )
                    for _c in _ceo_chunks[:3]:
                        logger.info(
                            f"  page={_c.page_number}  idx={_c.chunk_index}  "
                            f"text={_c.text[:300]!r}"
                        )
                else:
                    logger.warning(
                        f"[CEO DETECT] doc={document_id}  "
                        "no CEO/leadership text found in any chunk — "
                        "check if document uses different terminology"
                    )

                # ── Step 3: Embed in batches (thread executor, with retry) ────
                logger.info(
                    f"[EMBEDDING START] doc={document_id} "
                    f"chunks={len(chunks)} batch_size={EMBED_BATCH_SIZE}"
                )
                t_embed   = time.perf_counter()
                embedder  = get_embedder()
                embedding_model, embedding_version = get_embedding_identity()
                all_vecs: list[list[float]] = []

                for start in range(0, len(chunks), EMBED_BATCH_SIZE):
                    batch     = chunks[start : start + EMBED_BATCH_SIZE]
                    batch_end = start + len(batch)
                    vecs      = await _embed_with_retry(
                        embedder,
                        [c.text for c in batch],
                        document_id,
                        start,
                    )
                    all_vecs.extend(vecs)
                    logger.debug(
                        f"[EMBEDDING] doc={document_id} "
                        f"chunks {start}–{batch_end} / {len(chunks)} embedded"
                    )

                embed_ms = (time.perf_counter() - t_embed) * 1000
                logger.info(
                    f"[EMBEDDING COMPLETE] doc={document_id} "
                    f"vectors={len(all_vecs)} ({embed_ms:.0f}ms)"
                )

                # ── Embedding quality logging ─────────────────────────────────
                import math as _math
                if all_vecs:
                    _v0  = all_vecs[0]
                    _mag = _math.sqrt(sum(_x * _x for _x in _v0))
                    logger.info(
                        f"[EMBED SAMPLE] doc={document_id}  "
                        f"dim={len(_v0)}  "
                        f"magnitude={_mag:.4f}  "
                        f"expected_dim=384  "
                        f"first_5={[round(_x, 4) for _x in _v0[:5]]}"
                    )
                    if len(_v0) != 384:
                        logger.error(
                            f"[EMBED DIM MISMATCH] doc={document_id}  "
                            f"stored={len(_v0)}  expected=384  "
                            "All retrieval will fail. "
                            "Fix: change HF_EMBEDDING_MODEL back to "
                            "'sentence-transformers/all-MiniLM-L6-v2' and re-index."
                        )
                    if _mag < 0.01:
                        logger.error(
                            f"[EMBED ZERO VECTOR] doc={document_id}  "
                            "First vector is near-zero — embedding failed silently. "
                            "Check embedder logs above for errors."
                        )

                    # Count zero-vector embeddings across all batches
                    _zero_count = sum(
                        1 for _v in all_vecs
                        if _math.sqrt(sum(_x * _x for _x in _v)) < 0.01
                    )
                    if _zero_count:
                        logger.error(
                            f"[EMBED ZERO VECTORS] doc={document_id}  "
                            f"zero_vectors={_zero_count}/{len(all_vecs)}  "
                            "These chunks will never be retrieved."
                        )
                    else:
                        logger.info(
                            f"[EMBED QUALITY] doc={document_id}  "
                            f"all {len(all_vecs)} vectors non-zero  dim=384  OK"
                        )

            if len(all_vecs) != len(chunks):
                raise ValueError(
                    f"Embedding count mismatch: {len(all_vecs)} vectors "
                    f"for {len(chunks)} chunks."
                )

            # ── Step 4: Insert chunks in batches ─────────────────────────────
            logger.info(
                f"[VECTOR INSERT START] doc={document_id} "
                f"rows={len(chunks)} batch_size={INSERT_BATCH_SIZE}"
            )
            t_insert = time.perf_counter()

            for start in range(0, len(chunks), INSERT_BATCH_SIZE):
                end          = start + INSERT_BATCH_SIZE
                batch_chunks = chunks[start:end]
                batch_vecs   = all_vecs[start:end]
                db.add_all([
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        content=chunk.text,
                        page_number=chunk.page_number,
                        section_heading=chunk.section_heading or None,
                        category=infer_chunk_category(
                            chunk.section_heading,
                            chunk.text,
                            doc_name,
                        ),
                        source_document=doc_name,
                        embedding_model=embedding_model,
                        embedding_version=embedding_version,
                        extraction_metadata={
                            **(chunk.metadata or {}),
                            "source_document": doc_name,
                            "section_name": chunk.section_heading or None,
                            "chunk_id": chunk.chunk_index,
                            "upload_date": (
                                getattr(doc, "uploaded_at", None).isoformat()
                                if "doc" in locals() and getattr(doc, "uploaded_at", None)
                                else None
                            ),
                        },
                        embedding=vec,
                    )
                    for chunk, vec in zip(batch_chunks, batch_vecs)
                ])
                await db.flush()
                logger.debug(
                    f"[VECTOR INSERT] doc={document_id} "
                    f"flushed rows {start}–{end}"
                )

            insert_ms = (time.perf_counter() - t_insert) * 1000
            logger.info(
                f"[VECTOR INSERT COMPLETE] doc={document_id} "
                f"rows={len(chunks)} ({insert_ms:.0f}ms)"
            )

            # ── Step 5: Mark as indexed ───────────────────────────────────────
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status        = DocumentStatus.indexed,
                    chunk_count   = len(chunks),
                    page_count    = page_count,
                    indexed_at    = datetime.now(timezone.utc),
                    error_message = None,
                )
            )
            await db.commit()

            total_ms = (time.perf_counter() - t_total) * 1000
            logger.info(
                f"[DOCUMENT INDEXED] doc={document_id} name={doc_name!r} "
                f"chunks={len(chunks)} pages={page_count} "
                f"total={total_ms:.0f}ms "
                f"(parse={parse_ms:.0f}ms embed={embed_ms:.0f}ms insert={insert_ms:.0f}ms)"
            )
            await _safe_notify(
                user_id,
                "Indexing completed",
                f"'{doc_name}' is ready — {len(chunks)} chunks indexed.",
            )

        except Exception as exc:
            logger.error(
                f"[INDEXING FAILED] doc={document_id} — {exc}",
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            try:
                await db.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(
                        status        = DocumentStatus.failed,
                        error_message = str(exc)[:1000],
                    )
                )
                await db.commit()
            except Exception as db_exc:
                logger.error(
                    f"[INDEXING FAILED] doc={document_id} "
                    f"could not persist failed status: {db_exc}"
                )
            await _safe_notify(
                user_id,
                "Indexing failed",
                f"Could not index '{doc_name}'. Error: {str(exc)[:120]}",
                ntype="error",
            )
            return   # skip summary + domain on failure

    # ── Step 6: AI summary (separate session — non-fatal) ────────────────────
    try:
        summary = await _generate_summary(document_id, chunks)
        if summary:
            async with AsyncSessionLocal() as db2:
                await db2.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(summary=summary)
                )
                await db2.commit()
            await _safe_notify(
                user_id,
                "AI summary ready",
                f"Summary for '{doc_name}' has been generated.",
                ntype="ai",
            )
    except Exception as exc:
        logger.warning(
            f"[Indexing] Summary failed for {document_id} (non-fatal): {exc}"
        )

    # ── Step 7: Domain classification (separate session — non-fatal) ─────────
    try:
        from app.services.domain_classifier import classify_document_domain
        domain = await classify_document_domain(doc_name, chunks)
        if domain:
            async with AsyncSessionLocal() as db3:
                await db3.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(domain_name=domain)
                )
                await db3.commit()
            logger.info(f"[Domain] '{doc_name}' → '{domain}'")
    except Exception as exc:
        logger.warning(
            f"[Indexing] Domain classification failed for {document_id} (non-fatal): {exc}"
        )


# ── Summary helper ────────────────────────────────────────────────────────────

_SUMMARY_PROMPT = (
    "Summarize this document in 3 sentences covering: "
    "main topic, key information, and conclusions. "
    "Return only the summary text."
)


async def _generate_summary(document_id: uuid.UUID, chunks: list) -> str | None:
    try:
        from app.ai_providers import get_ai_provider
        provider = get_ai_provider()
        if hasattr(provider, "is_configured") and not provider.is_configured:
            return None

        sample_chunks = sorted(chunks, key=lambda c: c.chunk_index)[:5]
        combined      = "\n\n".join(c.text for c in sample_chunks)
        if not combined.strip():
            return None

        context   = f"<context>\n{combined[:6000]}\n</context>"
        full_text = ""
        async for token in provider.stream_chat(
            system_prompt=_SUMMARY_PROMPT,
            question="Generate the document summary as instructed.",
            context=context,
            conversation_history=None,
        ):
            full_text += token

        summary = full_text.strip()
        if summary:
            logger.info(
                f"[Indexing] Summary generated for {document_id} ({len(summary)} chars)"
            )
            return summary

    except Exception as exc:
        logger.warning(
            f"[Indexing] Summary generation failed for {document_id} (non-fatal): {exc}"
        )
    return None
