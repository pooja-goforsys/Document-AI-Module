"""
RAG Retrieval Diagnostic Router
================================
Endpoints for debugging the full RAG pipeline when retrieval fails despite
the answer existing in an uploaded document.

Endpoints
---------
POST /debug/retrieval   — full pipeline trace for one query
GET  /rag/health        — document / chunk / embedding counts + config
GET  /debug/chunks      — inspect raw chunks for a document
GET  /debug/embeddings  — verify embeddings for a document
"""
import uuid
import math
import logging
import time as _time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.config import settings
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.core import pgvector_search as _pv

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/debug", tags=["debug"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (duplicated locally so this file is self-contained)
# ─────────────────────────────────────────────────────────────────────────────

def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine distance with dimension-mismatch guard."""
    if len(a) != len(b):
        return -999.0  # flag: dimension mismatch
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


# ─────────────────────────────────────────────────────────────────────────────
# POST /debug/chat
# Runs the FULL chat path including a real LLM call and returns one JSON
# payload (no streaming). Use this to capture the exception when a normal
# /chat/query stream fails for a summary question.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def debug_chat(
    body: dict,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute one query end-to-end (retrieval → reranking → LLM) and capture
    every stage. If anything throws, the exception type, message, and
    traceback are returned in the payload instead of a 500.

    Request:
      {"query": "Summarize the chapter in 100 words",
       "document_id": "optional-uuid",
       "scope_type": "all|document",
       "max_response_chars": 4000}
    """
    import traceback as _tb
    import secrets
    from app.services.chat_service import (
        _intent_classify,
        _generate_search_variants,
        _retrieve_chunks,
        _calculate_confidence,
        _retrieval_confidence_gate,
        _format_context,
        _build_system_prompt,
        _fetch_scope_chunks_by_order,
        _INTENT_TOP_K,
    )
    from app.embedders import get_embedder
    from app.ai_providers import get_ordered_provider_chain

    query     = (body.get("query") or "").strip()
    doc_id    = body.get("document_id")
    max_out   = int(body.get("max_response_chars") or 4000)
    req_id    = secrets.token_hex(6)

    if not query:
        return {"error": "query field is required", "request_id": req_id}

    payload: dict = {
        "request_id":      req_id,
        "query":           query,
        "stage":           "init",
        "llm_called":      False,
        "llm_response":    None,
        "exception":       None,
        "exception_type":  None,
        "traceback":       None,
    }

    try:
        scope_type = "all"
        scope_id   = None
        if doc_id:
            scope_id   = uuid.UUID(str(doc_id))
            scope_type = "document"

        payload["stage"]  = "intent_classification"
        intent            = _intent_classify(query)
        variants          = _generate_search_variants(query, intent)
        payload["intent"] = intent
        payload["search_variants"] = variants

        payload["stage"]  = "embedding"
        embedder          = get_embedder()
        variant_vectors   = await embedder.embed_texts(variants)

        payload["stage"]  = "retrieval"
        rows = await _retrieve_chunks(
            variant_vectors, user_id, db, scope_type, scope_id,
            question=query, scope_name=None,
        )

        coverage_intents = {"summary", "list", "pageagg"}
        if intent in coverage_intents and (rows is None or len(rows) < 3):
            payload["stage"] = "fallback_fetch"
            target_n = _INTENT_TOP_K.get(intent, 15)
            fb_rows = await _fetch_scope_chunks_by_order(
                user_id=user_id, scope_type=scope_type, scope_id=scope_id,
                scope_name=None, limit=target_n, db=db,
            )
            payload["fallback_triggered"] = bool(fb_rows)
            if fb_rows:
                rows = fb_rows
        else:
            payload["fallback_triggered"] = False

        payload["retrieved_chunks"]  = len(rows)
        payload["similarity_scores"] = [round(1.0 - float(d), 4) for _, _, d in rows][:20]

        payload["stage"]     = "confidence"
        confidence, level    = _calculate_confidence(rows) if rows else (0.0, "low")
        payload["confidence"]       = confidence
        payload["confidence_level"] = level

        bypass = intent in coverage_intents and len(rows) >= 3
        gate_block = False
        if rows and not bypass:
            gate_block, gate_reason, _ = _retrieval_confidence_gate(rows, confidence)
            payload["gate_blocked"] = gate_block
            payload["gate_reason"]  = gate_reason
        payload["gate_bypassed"] = bypass

        if not rows or gate_block:
            payload["stage"] = "blocked_before_llm"
            return payload

        payload["stage"]            = "context_build"
        context_str, citations      = _format_context(rows)
        payload["context_length"]   = len(context_str)
        payload["token_estimate"]   = len(context_str) // 4

        payload["stage"]                 = "prompt_build"
        system_prompt                    = _build_system_prompt(
            scope_type, None, mode="auto", complexity="medium", intent=intent
        )
        payload["system_prompt_length"]  = len(system_prompt)

        chain = get_ordered_provider_chain()
        if not chain:
            payload["stage"]      = "no_provider"
            payload["exception"]  = "No AI provider is configured or healthy."
            return payload

        name, provider           = chain[0]
        payload["active_provider"] = name
        payload["stage"]         = "llm_call"

        collected: list[str] = []
        async for tok in provider.stream_chat(
            system_prompt, query, context_str, conversation_history=None,
        ):
            if tok:
                collected.append(tok)
                if sum(len(t) for t in collected) >= max_out:
                    break
        payload["llm_called"]   = True
        payload["llm_response"] = "".join(collected)
        payload["stage"]        = "complete"

    except Exception as exc:
        payload["exception"]      = str(exc)
        payload["exception_type"] = type(exc).__name__
        payload["traceback"]      = _tb.format_exc()
        logger.exception(f"[debug/chat {req_id}] failed at stage={payload.get('stage')}")

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# POST /debug/query
# Focused diagnostic for "why did this question fail" — returns intent,
# retrieved-chunk count, similarity scores, confidence, gate decision,
# context length, and whether the LLM would be called. Does NOT call the LLM.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/query")
async def debug_query(
    body: dict,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run the retrieval + gate pipeline for one query and return diagnostics.

    Request:
      {"query": "Summarize the chapter in 100 words",
       "document_id": "optional-uuid",
       "include_context": false}
    """
    from app.services.chat_service import (
        _intent_classify,
        _generate_search_variants,
        _retrieve_chunks,
        _calculate_confidence,
        _retrieval_confidence_gate,
        _format_context,
        _build_system_prompt,
        _fetch_scope_chunks_by_order,
        _INTENT_TOP_K,
    )
    from app.embedders import get_embedder

    query           = (body.get("query") or "").strip()
    doc_id_raw      = body.get("document_id")
    include_context = bool(body.get("include_context", False))

    if not query:
        return {"error": "query field is required"}

    scope_type = "all"
    scope_id   = None
    scope_name = None
    if doc_id_raw:
        try:
            scope_id   = uuid.UUID(str(doc_id_raw))
            scope_type = "document"
        except (ValueError, TypeError):
            return {"error": f"invalid document_id: {doc_id_raw!r}"}

    intent   = _intent_classify(query)
    variants = _generate_search_variants(query, intent)

    embedder = get_embedder()
    variant_vectors = await embedder.embed_texts(variants)

    rows = await _retrieve_chunks(
        variant_vectors, user_id, db, scope_type, scope_id,
        question=query, scope_name=scope_name,
    )

    coverage_intents = {"summary", "list", "pageagg"}
    fallback_triggered = False
    fallback_reason    = None
    if intent in coverage_intents and (rows is None or len(rows) < 3):
        target_n = _INTENT_TOP_K.get(intent, 15)
        fb_rows = await _fetch_scope_chunks_by_order(
            user_id=user_id, scope_type=scope_type, scope_id=scope_id,
            scope_name=scope_name, limit=target_n, db=db,
        )
        if fb_rows:
            fallback_triggered = True
            fallback_reason    = (
                f"intent={intent} returned {0 if not rows else len(rows)} chunks; "
                f"fetched {len(fb_rows)} by document order"
            )
            rows = fb_rows

    similarity_scores = [round(1.0 - float(d), 4) for _, _, d in rows]
    confidence, conf_level = _calculate_confidence(rows) if rows else (0.0, "low")

    gate_block, gate_reason, gate_scores = False, "", {}
    bypass_gate = intent in coverage_intents and len(rows) >= 3
    if rows and not bypass_gate:
        gate_block, gate_reason, gate_scores = _retrieval_confidence_gate(rows, confidence)

    context_str   = ""
    citation_list = []
    if rows:
        context_str, citation_list = _format_context(rows)

    system_prompt = _build_system_prompt(
        scope_type, scope_name, mode="auto", complexity="medium", intent=intent
    )

    llm_will_be_called = bool(rows) and not gate_block

    payload: dict = {
        "query":             query,
        "intent":            intent,
        "search_variants":   variants,
        "retrieved_chunks":  len(rows),
        "chunk_ids":         [str(c.id) for c, _, _ in rows[:50]],
        "similarity_scores": similarity_scores[:50],
        "confidence":        confidence,
        "confidence_level":  conf_level,
        "context_length":    len(context_str),
        "system_prompt_length": len(system_prompt),
        "gate_blocked":      gate_block,
        "gate_reason":       gate_reason or None,
        "gate_scores":       gate_scores or None,
        "gate_bypassed":     bypass_gate,
        "fallback_triggered": fallback_triggered,
        "fallback_reason":   fallback_reason,
        "llm_called":        llm_will_be_called,
        "sources_preview":   [
            {
                "document":  doc.original_name,
                "page":      getattr(c, "page_number", None),
                "section":   getattr(c, "section_heading", None),
                "similarity": round(1.0 - float(d), 4),
            }
            for c, doc, d in rows[:20]
        ],
    }
    if include_context:
        payload["context"] = context_str
        payload["system_prompt"] = system_prompt
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# TASK 8 — POST /debug/retrieval
# Full pipeline trace: embed → vector search → keyword search → entity search
# → rerank → context assembly → prompt preview
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/retrieval")
async def debug_retrieval(
    body: dict,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trace the full retrieval pipeline for a query and return every
    intermediate result so you can pinpoint exactly where it breaks.

    Request body:
        {"query": "Who is the CEO of Microsoft?",
         "document_id": "optional-uuid-string",
         "top_k": 20}

    Response contains every pipeline stage with scores and chunk text.
    """
    query       = (body.get("query") or "").strip()
    doc_id_raw  = body.get("document_id")
    top_k       = int(body.get("top_k") or 20)

    if not query:
        return {"error": "query field is required"}

    t0 = _time.monotonic()
    report: dict = {
        "query": query,
        "pipeline_stages": {},
        "elapsed_ms": 0,
    }

    # ── Stage 0a: Provider health ─────────────────────────────────────────────
    from app.ai_providers import (
        get_provider_health, get_fallback_provider_name, get_ai_provider,
    )
    _primary = settings.AI_PROVIDER
    _primary_health = get_provider_health(_primary)
    _fb_name = get_fallback_provider_name()

    try:
        _prov = get_ai_provider()
        _prov_configured = getattr(_prov, "is_configured", True)
    except Exception as _pe:
        _prov_configured = False

    report["pipeline_stages"]["stage_0a_provider_health"] = {
        "description": "AI provider availability and health status",
        "primary_provider":      _primary,
        "primary_healthy":       _primary_health["healthy"],
        "primary_error_type":    _primary_health["error_type"],
        "primary_configured":    _prov_configured,
        "fallback_provider":     _fb_name,
        "fallback_available":    _fb_name is not None,
        "diagnosis": (
            f"OK — {_primary} is healthy and configured"
            if _primary_health["healthy"] and _prov_configured
            else f"DEGRADED — {_primary} is unhealthy (type={_primary_health['error_type']}), "
                 + (f"fallback={_fb_name} available" if _fb_name else "no fallback configured")
            if not _primary_health["healthy"]
            else f"PROBLEM — {_primary} API key not configured"
        ),
    }

    # ── Stage 0b: Document inventory ──────────────────────────────────────────
    doc_stmt = (
        select(
            Document.id, Document.original_name, Document.status,
            Document.chunk_count, Document.page_count, Document.file_type,
            Document.domain_name,
        )
        .where(Document.user_id == user_id)
    )
    if doc_id_raw:
        try:
            doc_stmt = doc_stmt.where(Document.id == uuid.UUID(doc_id_raw))
        except ValueError:
            return {"error": f"invalid document_id: {doc_id_raw!r}"}

    doc_rows = (await db.execute(doc_stmt)).all()
    report["pipeline_stages"]["stage_0b_documents"] = {
        "description": "All documents visible to this user",
        "count": len(doc_rows),
        "documents": [
            {
                "id":          str(r.id),
                "name":        r.original_name,
                "status":      r.status,
                "chunk_count": r.chunk_count,
                "page_count":  r.page_count,
                "file_type":   r.file_type,
                "domain":      r.domain_name,
            }
            for r in doc_rows
        ],
        "diagnosis": (
            "OK — indexed documents found"
            if any(r.status == "indexed" for r in doc_rows)
            else "PROBLEM — no indexed documents (check status column above)"
        ),
    }

    # ── Stage 1: Query embedding ──────────────────────────────────────────────
    from app.embedders import get_embedder
    from app.services.chat_service import _expand_query

    expanded_query = _expand_query(query)
    try:
        embedder  = get_embedder()
        q_vector  = await embedder.embed_query(expanded_query)
        embed_dim = len(q_vector)
        embed_ok  = True
        embed_err = None
    except Exception as exc:
        q_vector  = []
        embed_dim = 0
        embed_ok  = False
        embed_err = str(exc)

    report["pipeline_stages"]["stage_1_embedding"] = {
        "description": "Query embedding generation",
        "model":           settings.HF_EMBEDDING_MODEL,
        "expected_dim":    settings.EMBEDDING_DIMENSION,
        "actual_dim":      embed_dim,
        "expanded_query":  expanded_query,
        "ok":              embed_ok,
        "error":           embed_err,
        "diagnosis": (
            "OK" if embed_ok and embed_dim == settings.EMBEDDING_DIMENSION
            else f"PROBLEM — dim mismatch ({embed_dim} vs {settings.EMBEDDING_DIMENSION})"
            if embed_ok
            else f"PROBLEM — embedding failed: {embed_err}"
        ),
    }

    if not embed_ok or not q_vector:
        report["elapsed_ms"] = round((_time.monotonic() - t0) * 1000)
        return report

    # ── Stage 2: Raw vector search (top-20 by cosine distance) ───────────────
    chunk_stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
        .where(DocumentChunk.embedding.is_not(None))
    )
    if doc_id_raw:
        chunk_stmt = chunk_stmt.where(Document.id == uuid.UUID(doc_id_raw))

    all_chunks = (await db.execute(chunk_stmt)).all()

    vector_results = []
    dim_mismatches = 0
    null_embeddings = 0
    for chunk, doc in all_chunks:
        if chunk.embedding is None:
            null_embeddings += 1
            continue
        stored_dim = len(chunk.embedding)
        if stored_dim != embed_dim:
            dim_mismatches += 1
            vector_results.append({
                "chunk_id":     str(chunk.id),
                "document":     doc.original_name,
                "page":         chunk.page_number,
                "stored_dim":   stored_dim,
                "distance":     None,
                "similarity":   None,
                "content_preview": (chunk.content or "")[:120],
                "ERROR":        f"DIM MISMATCH — stored={stored_dim} vs query={embed_dim}",
            })
            continue

        dist = _cosine_distance(q_vector, chunk.embedding)
        # Extract section heading — from new column, or from [HEADING] prefix
        _sec = getattr(chunk, "section_heading", None) or ""
        if not _sec:
            _ct = chunk.content or ""
            if _ct.startswith("["):
                _end = _ct.find("]")
                if 0 < _end < 200:
                    _sec = _ct[1:_end]
        vector_results.append({
            "chunk_id":        str(chunk.id),
            "document":        doc.original_name,
            "page":            chunk.page_number,
            "section":         _sec[:80] if _sec else None,
            "stored_dim":      stored_dim,
            "distance":        round(dist, 6),
            "similarity":      round(1 - dist, 6),
            "passes_threshold": dist < settings.MAX_RETRIEVAL_DISTANCE,
            "content_preview": (chunk.content or "")[:120],
        })

    vector_results.sort(key=lambda x: (x.get("distance") or 2.0))
    top20 = vector_results[:20]

    passes = [r for r in vector_results if r.get("passes_threshold")]
    report["pipeline_stages"]["stage_2_vector_search"] = {
        "description": "Python cosine distance over all indexed chunks",
        "pgvector_native": _pv.is_available(),
        "total_chunks_scanned": len(all_chunks),
        "null_embeddings":      null_embeddings,
        "dim_mismatches":       dim_mismatches,
        "chunks_passing_threshold": len(passes),
        "threshold": settings.MAX_RETRIEVAL_DISTANCE,
        "top_20_results": top20,
        "diagnosis": (
            f"OK — {len(passes)} chunks pass threshold"
            if passes and not dim_mismatches
            else f"PROBLEM — {dim_mismatches} dim-mismatch chunks (re-index needed)"
            if dim_mismatches
            else "PROBLEM — 0 chunks passed threshold (all similarity < 0.03)"
            if not passes
            else "OK"
        ),
    }

    # ── Stage 3: Keyword (FTS) search ────────────────────────────────────────
    kw_results = []
    kw_error   = None
    try:
        fts_stmt = (
            select(DocumentChunk.id, DocumentChunk.content,
                   DocumentChunk.page_number, Document.original_name)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.indexed)
            .where(DocumentChunk.embedding.is_not(None))
            .where(text(
                "to_tsvector('english', document_chunks.content) "
                "@@ plainto_tsquery('english', :q)"
            ).bindparams(q=query))
            .order_by(text(
                "ts_rank(to_tsvector('english', document_chunks.content), "
                "plainto_tsquery('english', :q))"
            ).bindparams(q=query).desc())
            .limit(30)
        )
        if doc_id_raw:
            fts_stmt = fts_stmt.where(Document.id == uuid.UUID(doc_id_raw))

        for row in (await db.execute(fts_stmt)).all():
            kw_results.append({
                "chunk_id":        str(row.id),
                "document":        row.original_name,
                "page":            row.page_number,
                "content_preview": (row.content or "")[:120],
            })
    except Exception as exc:
        kw_error = str(exc)

    report["pipeline_stages"]["stage_3_keyword_fts"] = {
        "description": "PostgreSQL full-text search",
        "enabled": settings.HYBRID_SEARCH_ENABLED,
        "result_count": len(kw_results),
        "error": kw_error,
        "results": kw_results[:10],
        "diagnosis": (
            f"OK — {len(kw_results)} FTS matches"
            if kw_results
            else f"PROBLEM — FTS error: {kw_error}"
            if kw_error
            else "WARNING — 0 FTS matches (document terms not in FTS index or query is all stopwords)"
        ),
    }

    # ── Stage 4: Entity / ILIKE search ───────────────────────────────────────
    from app.services.chat_service import _extract_query_entities

    entities = _extract_query_entities(query)
    entity_results: dict[str, list] = {}
    for entity in entities[:6]:
        ilike_stmt = (
            select(DocumentChunk.id, DocumentChunk.content,
                   DocumentChunk.page_number, Document.original_name)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.indexed)
            .where(DocumentChunk.content.ilike(f"%{entity}%"))
            .limit(10)
        )
        if doc_id_raw:
            ilike_stmt = ilike_stmt.where(Document.id == uuid.UUID(doc_id_raw))

        rows = (await db.execute(ilike_stmt)).all()
        entity_results[entity] = [
            {
                "chunk_id":        str(r.id),
                "document":        r.original_name,
                "page":            r.page_number,
                "content_preview": (r.content or "")[:120],
            }
            for r in rows
        ]

    total_entity_hits = sum(len(v) for v in entity_results.values())
    report["pipeline_stages"]["stage_4_entity_ilike"] = {
        "description": "ILIKE search for proper nouns / acronyms extracted from query",
        "entities_extracted": entities,
        "total_hits": total_entity_hits,
        "per_entity": entity_results,
        "diagnosis": (
            f"OK — {total_entity_hits} ILIKE hits across entities {entities}"
            if total_entity_hits
            else f"WARNING — 0 ILIKE hits for entities {entities}. "
                 "Possible cause: document uses 'Chief Executive Officer' not 'CEO'"
        ),
    }

    # ── Stage 5: Manual text search (guaranteed to find if text exists) ──────
    # Search for the exact words the answer would contain
    search_terms = ["CEO", "Chief Executive Officer", "Chairman", "Satya Nadella",
                    "Nadella", "chief executive"]
    text_search_results: dict[str, list] = {}
    for term in search_terms:
        ts_stmt = (
            select(DocumentChunk.id, DocumentChunk.content,
                   DocumentChunk.page_number, Document.original_name)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.indexed)
            .where(DocumentChunk.content.ilike(f"%{term}%"))
            .limit(5)
        )
        if doc_id_raw:
            ts_stmt = ts_stmt.where(Document.id == uuid.UUID(doc_id_raw))

        rows = (await db.execute(ts_stmt)).all()
        text_search_results[term] = [
            {
                "chunk_id":        str(r.id),
                "document":        r.original_name,
                "page":            r.page_number,
                "content_preview": (r.content or "")[:200],
            }
            for r in rows
        ]

    found_any = any(len(v) > 0 for v in text_search_results.values())
    report["pipeline_stages"]["stage_5_text_scan"] = {
        "description": "Direct ILIKE scan for CEO-related terms in chunks",
        "note": "If these return 0 results, the text was NOT extracted/chunked correctly",
        "per_term": text_search_results,
        "diagnosis": (
            f"OK — CEO text found in chunks"
            if found_any
            else "PROBLEM — CEO text not found in any chunk. "
                 "Extraction or chunking failed, OR document is a scanned image PDF."
        ),
    }

    # ── Stage 6: Cross-encoder scores (if reranker available) ────────────────
    if passes and settings.RERANKER_ENABLED:
        try:
            from app.services.reranker import _load_model, _sigmoid
            model = _load_model()
            ce_results = []
            if model:
                top_chunks_for_ce = passes[:10]
                pairs = [(query, (r.get("content_preview") or ""))
                         for r in top_chunks_for_ce]
                raw_scores = model.predict(pairs)
                for i, r in enumerate(top_chunks_for_ce):
                    ce_results.append({
                        "chunk_id":        r["chunk_id"],
                        "document":        r["document"],
                        "page":            r["page"],
                        "ce_score":        round(_sigmoid(float(raw_scores[i])), 4),
                        "be_similarity":   r["similarity"],
                        "content_preview": r["content_preview"],
                        "passes_min_score": _sigmoid(float(raw_scores[i])) >= settings.RERANKER_MIN_SCORE,
                    })
                ce_results.sort(key=lambda x: x["ce_score"], reverse=True)

            above_min = [r for r in ce_results if r.get("passes_min_score")]
            report["pipeline_stages"]["stage_6_reranker"] = {
                "description": "Cross-encoder reranker scores",
                "model":       settings.RERANKER_MODEL,
                "min_score":   settings.RERANKER_MIN_SCORE,
                "min_results": settings.RERANKER_MIN_RESULTS,
                "scores":      ce_results,
                "above_threshold": len(above_min),
                "diagnosis": (
                    f"OK — {len(above_min)} chunks above min_score={settings.RERANKER_MIN_SCORE}"
                    if above_min
                    else f"WARNING — all chunks below min_score={settings.RERANKER_MIN_SCORE} "
                         f"(min_results={settings.RERANKER_MIN_RESULTS} will be used as fallback)"
                ),
            }
        except Exception as exc:
            report["pipeline_stages"]["stage_6_reranker"] = {
                "error": str(exc),
                "diagnosis": f"PROBLEM — reranker unavailable: {exc}",
            }

    # ── Stage 6b: Retrieval validation (cross-domain check) ──────────────────
    if passes and query:
        try:
            from app.services.chat_service import _validate_retrieval, _intent_classify
            _intent = _intent_classify(query)
            _pass_triples = [
                (chunk_doc_map.get(r["chunk_id"], (None, None)) + (r["distance"],))
                for r in passes[:settings.RERANKER_TOP_K]
                if r["chunk_id"] in {str(c.id): (c, d) for c, d in all_chunks}
            ] if "chunk_doc_map" in dir() else []

            # Rebuild chunk_doc_map if not yet set
            if not _pass_triples:
                _cdm = {str(c.id): (c, d) for c, d in all_chunks}
                _pass_triples = [
                    (_cdm[r["chunk_id"]][0], _cdm[r["chunk_id"]][1], r["distance"])
                    for r in passes[:settings.RERANKER_TOP_K]
                    if r["chunk_id"] in _cdm
                ]

            if _pass_triples:
                _filtered, _issues = _validate_retrieval(_pass_triples, query, _intent)
                report["pipeline_stages"]["stage_6b_retrieval_validation"] = {
                    "description": "Cross-domain contamination and intent alignment check",
                    "intent":             _intent,
                    "input_chunks":       len(_pass_triples),
                    "filtered_chunks":    len(_filtered),
                    "removed":            len(_pass_triples) - len(_filtered),
                    "issues":             _issues,
                    "diagnosis": (
                        f"OK — no cross-domain issues detected"
                        if not _issues
                        else f"WARNING — {len(_issues)} retrieval issue(s): {_issues[:2]}"
                    ),
                }
        except Exception as _rv_exc:
            report["pipeline_stages"]["stage_6b_retrieval_validation"] = {
                "error": str(_rv_exc),
                "diagnosis": f"PROBLEM — validation unavailable: {_rv_exc}",
            }

    # ── Stage 7: Context preview ──────────────────────────────────────────────
    top_for_context = passes[:settings.RERANKER_TOP_K]
    if top_for_context:
        from app.services.chat_service import _format_context
        # Reconstruct (chunk, doc, dist) triples from the scored results
        # Build a lookup from chunk_id to (chunk, doc) objects
        chunk_doc_map = {str(c.id): (c, d) for c, d in all_chunks}
        triples = []
        for r in top_for_context:
            cid = r["chunk_id"]
            if cid in chunk_doc_map:
                c, d = chunk_doc_map[cid]
                triples.append((c, d, r["distance"]))

        if triples:
            ctx, citations = _format_context(triples[:settings.RERANKER_TOP_K])
            report["pipeline_stages"]["stage_7_context"] = {
                "description": "Context block sent to LLM",
                "context_length_chars": len(ctx),
                "citation_count": len(citations),
                "context_preview": ctx[:2000],
                "diagnosis": "OK — context assembled" if ctx else "PROBLEM — empty context",
            }

    # ── Summary ───────────────────────────────────────────────────────────────
    report["elapsed_ms"] = round((_time.monotonic() - t0) * 1000)
    report["summary"] = _build_diagnosis_summary(report["pipeline_stages"])
    return report


def _build_diagnosis_summary(stages: dict) -> dict:
    """Produce a top-level diagnosis from all stage results."""
    problems = []
    warnings = []

    for name, stage in stages.items():
        diag = stage.get("diagnosis", "")
        if diag.startswith("PROBLEM"):
            problems.append(f"{name}: {diag}")
        elif diag.startswith("WARNING"):
            warnings.append(f"{name}: {diag}")

    if problems:
        most_likely = problems[0]
    elif warnings:
        most_likely = warnings[0]
    else:
        most_likely = "Pipeline looks healthy — check provider key and prompt filtering"

    return {
        "problems":    problems,
        "warnings":    warnings,
        "most_likely_failure": most_likely,
        "fix_hint": _fix_hint(problems, warnings),
    }


def _fix_hint(problems: list, warnings: list) -> str:
    all_msgs = " ".join(problems + warnings).lower()
    if "not indexed" in all_msgs or "no indexed" in all_msgs:
        return "Check document status in DB: SELECT id, original_name, status, error_message FROM documents WHERE user_id = <your_id>;"
    if "dim mismatch" in all_msgs:
        return "Re-index all documents: DELETE FROM document_chunks; UPDATE documents SET status='pending'; then restart server."
    if "ceo text not found" in all_msgs or "text was not extracted" in all_msgs:
        return "Document text extraction failed. Check if the PDF is a scanned image (needs OCR). Try uploading as DOCX or TXT."
    if "0 fts matches" in all_msgs:
        return "FTS index may be stale. Run: REINDEX TABLE document_chunks; or check if FTS config 'english' is installed."
    if "embedding failed" in all_msgs:
        return "Embedding model failed to load. Check internet connection for first download or set HF_EMBEDDING_MODEL to an available model."
    if "api key" in all_msgs:
        return "Add GEMINI_API_KEY=<your_key> to backend/.env and restart."
    return "Check backend logs for the failing stage. Run: uvicorn app.main:app --log-level debug"


# ─────────────────────────────────────────────────────────────────────────────
# TASK 9 — GET /rag/health
# Document / chunk / embedding counts + system config
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health", include_in_schema=True)
@router.get("/rag/health", include_in_schema=True)
async def rag_health(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    RAG system health check — returns counts, config, and status for every
    component in the pipeline.
    """
    # ── Document counts ───────────────────────────────────────────────────────
    doc_counts = (await db.execute(
        select(Document.status, func.count(Document.id).label("n"))
        .where(Document.user_id == user_id)
        .group_by(Document.status)
    )).all()
    doc_by_status = {row.status: row.n for row in doc_counts}
    total_docs    = sum(doc_by_status.values())

    # ── Chunk / embedding counts ──────────────────────────────────────────────
    chunk_stats = (await db.execute(
        select(
            func.count(DocumentChunk.id).label("total"),
            func.count(DocumentChunk.embedding).label("with_embedding"),
            func.avg(func.length(DocumentChunk.content)).label("avg_len"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
    )).one()

    total_chunks     = chunk_stats.total or 0
    chunks_with_emb  = chunk_stats.with_embedding or 0
    avg_chunk_size   = round(float(chunk_stats.avg_len or 0))

    # ── Embedding dimension sample ────────────────────────────────────────────
    sample_emb = (await db.execute(
        select(DocumentChunk.embedding)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
        .where(DocumentChunk.embedding.is_not(None))
        .limit(1)
    )).scalar()
    stored_dim = len(sample_emb) if sample_emb else None

    # ── AI provider status (with health cache) ────────────────────────────────
    from app.ai_providers import (
        get_provider_health, get_fallback_provider_name,
    )
    gemini_key = (settings.GEMINI_API_KEY or "").strip()
    _placeholders = {"", "your_gemini_api_key_here", "your-api-key", "placeholder"}
    gemini_ok  = bool(gemini_key) and gemini_key.lower() not in _placeholders

    _primary_health  = get_provider_health(settings.AI_PROVIDER)
    _fb_provider     = get_fallback_provider_name()

    # ── Determine overall status ──────────────────────────────────────────────
    indexed_docs    = doc_by_status.get("indexed", 0)
    missing_embeddings = total_chunks - chunks_with_emb
    dim_ok = (stored_dim == settings.EMBEDDING_DIMENSION) if stored_dim else None

    issues = []
    if indexed_docs == 0:
        issues.append("no indexed documents")
    if missing_embeddings > 0:
        issues.append(f"{missing_embeddings} chunks missing embeddings")
    if dim_ok is False:
        issues.append(
            f"embedding dimension mismatch: stored={stored_dim} config={settings.EMBEDDING_DIMENSION}"
        )
    if not gemini_ok:
        issues.append("GEMINI_API_KEY not configured")
    if not _primary_health["healthy"]:
        issues.append(
            f"primary provider {settings.AI_PROVIDER!r} unhealthy "
            f"(type={_primary_health['error_type']}) — "
            + (f"failover to {_fb_provider!r} active" if _fb_provider else "no fallback configured")
        )
    if not _pv.is_available():
        issues.append("pgvector extension not installed (Python cosine fallback active)")

    overall = "healthy" if not issues else ("degraded" if indexed_docs > 0 else "unhealthy")

    return {
        "status": overall,
        "issues": issues,

        "documents": {
            "total":      total_docs,
            "indexed":    doc_by_status.get("indexed",  0),
            "pending":    doc_by_status.get("pending",  0),
            "indexing":   doc_by_status.get("indexing", 0),
            "failed":     doc_by_status.get("failed",   0),
        },

        "chunks": {
            "total":             total_chunks,
            "with_embeddings":   chunks_with_emb,
            "without_embeddings": missing_embeddings,
            "avg_chunk_size_chars": avg_chunk_size,
        },

        "embeddings": {
            "stored_dimension":   stored_dim,
            "config_dimension":   settings.EMBEDDING_DIMENSION,
            "dimension_match":    dim_ok,
            "model":              settings.HF_EMBEDDING_MODEL,
        },

        "vector_search": {
            "pgvector_native":    _pv.is_available(),
            "mode":               "pgvector_native" if _pv.is_available() else "python_cosine_fallback",
            "candidates":         settings.VECTOR_SEARCH_CANDIDATES,
            "max_distance":       settings.MAX_RETRIEVAL_DISTANCE,
        },

        "reranker": {
            "enabled":    settings.RERANKER_ENABLED,
            "model":      settings.RERANKER_MODEL,
            "top_k":      settings.RERANKER_TOP_K,
            "min_score":  settings.RERANKER_MIN_SCORE,
            "min_results": settings.RERANKER_MIN_RESULTS,
        },

        "hybrid_search": {
            "enabled":       settings.HYBRID_SEARCH_ENABLED,
            "keyword_boost": settings.HYBRID_SEARCH_KEYWORD_BOOST,
            "max_per_page":  settings.MAX_CHUNKS_PER_PAGE,
        },

        "ai": {
            "provider":           settings.AI_PROVIDER,
            "model":              settings.GEMINI_MODEL,
            "key_configured":     gemini_ok,
            "provider_healthy":   _primary_health["healthy"],
            "provider_error_type": _primary_health["error_type"],
            "fallback_provider":  _fb_provider,
            "health_ttl_seconds": settings.PROVIDER_HEALTH_TTL,
        },

        "retrieval_validation": {
            "enabled":              settings.RETRIEVAL_VALIDATION_ENABLED,
            "contamination_check":  settings.CHUNK_CONTAMINATION_CHECK,
        },

        "chunk_config": {
            "size":    settings.CHUNK_SIZE,
            "overlap": settings.CHUNK_OVERLAP,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/chunks — inspect raw extracted chunks for a document
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/chunks")
async def inspect_chunks(
    document_id: str = Query(..., description="Document UUID"),
    page: int | None = Query(None, description="Filter to this page number"),
    search: str | None = Query(None, description="Search text in chunks (ILIKE)"),
    limit: int = Query(50, le=500),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return raw chunks for a document so you can verify that the answer text
    was actually extracted and stored correctly.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        return {"error": f"invalid document_id: {document_id!r}"}

    doc = await db.get(Document, doc_uuid)
    if not doc or doc.user_id != user_id:
        return {"error": "document not found"}

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_uuid)
        .order_by(DocumentChunk.chunk_index)
    )
    if page is not None:
        stmt = stmt.where(DocumentChunk.page_number == page)
    if search:
        stmt = stmt.where(DocumentChunk.content.ilike(f"%{search}%"))
    stmt = stmt.limit(limit)

    chunks = (await db.execute(stmt)).scalars().all()

    return {
        "document": {
            "id":          str(doc.id),
            "name":        doc.original_name,
            "status":      doc.status,
            "chunk_count": doc.chunk_count,
            "page_count":  doc.page_count,
            "file_type":   doc.file_type,
        },
        "filters": {"page": page, "search": search},
        "returned": len(chunks),
        "chunks": [
            {
                "chunk_index":    c.chunk_index,
                "page_number":    c.page_number,
                "section_heading": getattr(c, "section_heading", None),
                "chunk_id":       str(c.id),
                "has_embedding":  c.embedding is not None,
                "embedding_dim":  len(c.embedding) if c.embedding else None,
                "content_length": len(c.content or ""),
                "content":        c.content,
            }
            for c in chunks
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/embeddings — verify embedding quality for a document
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/embeddings")
async def inspect_embeddings(
    document_id: str = Query(...),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify that all chunks for a document have embeddings of the correct
    dimension, and that embeddings are not zero vectors.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        return {"error": f"invalid document_id: {document_id!r}"}

    doc = await db.get(Document, doc_uuid)
    if not doc or doc.user_id != user_id:
        return {"error": "document not found"}

    chunks = (await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_uuid)
        .order_by(DocumentChunk.chunk_index)
    )).scalars().all()

    issues   = []
    per_chunk = []
    for c in chunks:
        emb = c.embedding
        if emb is None:
            issues.append(f"chunk_index={c.chunk_index} — NULL embedding")
            per_chunk.append({
                "chunk_index": c.chunk_index,
                "status":      "NULL",
                "dim":         None,
            })
            continue

        dim   = len(emb)
        mag   = math.sqrt(sum(x * x for x in emb))
        zeros = sum(1 for x in emb if x == 0.0)

        chunk_status = "OK"
        if dim != settings.EMBEDDING_DIMENSION:
            chunk_status = f"DIM_MISMATCH (stored={dim} expected={settings.EMBEDDING_DIMENSION})"
            issues.append(f"chunk_index={c.chunk_index} — {chunk_status}")
        elif mag < 1e-9:
            chunk_status = "ZERO_VECTOR"
            issues.append(f"chunk_index={c.chunk_index} — zero vector (embedding failed silently)")
        elif mag < 0.5:
            chunk_status = f"LOW_MAGNITUDE (mag={mag:.4f})"

        per_chunk.append({
            "chunk_index": c.chunk_index,
            "page":        c.page_number,
            "status":      chunk_status,
            "dim":         dim,
            "magnitude":   round(mag, 6),
            "zero_values": zeros,
            "content_preview": (c.content or "")[:80],
        })

    total    = len(chunks)
    ok_count = sum(1 for c in per_chunk if c["status"] == "OK")

    return {
        "document": {
            "id":   str(doc.id),
            "name": doc.original_name,
        },
        "summary": {
            "total_chunks":     total,
            "ok":               ok_count,
            "with_issues":      total - ok_count,
            "issues":           issues[:20],
            "overall_status":   "OK" if not issues else "PROBLEMS FOUND",
        },
        "expected_dim":  settings.EMBEDDING_DIMENSION,
        "embedding_model": settings.HF_EMBEDDING_MODEL,
        "per_chunk": per_chunk,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/pgvector-test — test pgvector availability and speed
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/pgvector-test")
async def pgvector_test(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test whether pgvector is functional and measure query time."""
    results = {"pgvector_available": _pv.is_available()}

    # Test 1: extension installed?
    try:
        await db.execute(text("SELECT '[0.1,0.2,0.3]'::vector(3) <=> '[0.1,0.2,0.4]'::vector(3)"))
        results["extension_test"] = "PASS"
    except Exception as exc:
        results["extension_test"] = f"FAIL — {exc}"

    # Test 2: can we cast ARRAY(Float) to vector?
    try:
        row = (await db.execute(
            select(DocumentChunk.embedding)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.indexed)
            .where(DocumentChunk.embedding.is_not(None))
            .limit(1)
        )).scalar()

        if row:
            dim = len(row)
            sample = ",".join(f"{v:.8f}" for v in row[:5])
            results["sample_embedding"] = {
                "dim": dim,
                "first_5_values": sample,
                "magnitude": round(math.sqrt(sum(x * x for x in row)), 6),
            }

            # Test native vector cast
            t0 = _time.monotonic()
            await db.execute(text(
                f"SELECT embedding::vector({dim}) <=> embedding::vector({dim}) "
                "FROM document_chunks LIMIT 1"
            ))
            results["vector_cast_ms"] = round((_time.monotonic() - t0) * 1000, 2)
            results["vector_cast_test"] = "PASS"
        else:
            results["sample_embedding"] = "no indexed chunks found"
    except Exception as exc:
        results["vector_cast_test"] = f"FAIL — {exc}"

    return results


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/provider-health
# Live AI provider diagnostics — checks every configured provider and returns
# a status report with actionable fix instructions.
# ─────────────────────────────────────────────────────────────────────────────

_GEMINI_KEY_PREFIX = "AIzaSy"
_OPENAI_KEY_PREFIX = "sk-"
_ANTHROPIC_KEY_PREFIX = "sk-ant-"

_PROVIDER_FIX = {
    "gemini": (
        "1. Go to https://aistudio.google.com/app/apikey\n"
        "2. Create a free key (starts with 'AIzaSy')\n"
        "3. Add to backend/.env:  GEMINI_API_KEY=AIzaSy...\n"
        "4. Restart the server"
    ),
    "openai": (
        "1. Go to https://platform.openai.com/api-keys\n"
        "2. Create a key (starts with 'sk-')\n"
        "3. Add to backend/.env:  OPENAI_API_KEY=sk-...\n"
        "4. Restart the server"
    ),
    "anthropic": (
        "1. Go to https://console.anthropic.com/settings/keys\n"
        "2. Create a key (starts with 'sk-ant-')\n"
        "3. Add to backend/.env:  ANTHROPIC_API_KEY=sk-ant-...\n"
        "4. Restart the server"
    ),
    "local": (
        "1. Start Ollama:  ollama serve\n"
        "2. Pull a model:  ollama pull llama3.2\n"
        "3. Add to backend/.env:  LOCAL_MODEL_ENDPOINT=http://localhost:11434\n"
        "4. Restart the server"
    ),
}


@router.get("/provider-health")
async def provider_health(
    user_id: uuid.UUID = Depends(get_current_user),
):
    """
    Check the configuration status of every AI provider.

    Returns which providers are configured, which are unhealthy, and what
    to do to fix each one. No actual LLM call is made — this is config-only.
    """
    from app.ai_providers import (
        get_ordered_provider_chain,
        get_provider_health,
        _is_provider_configured,
    )

    _PROVIDER_NAMES = ["gemini", "openai", "anthropic", "local"]

    providers = {}
    for name in _PROVIDER_NAMES:
        configured = _is_provider_configured(name)
        health     = get_provider_health(name)

        key_format_ok = True
        key_hint      = None

        if name == "gemini":
            key = (settings.GEMINI_API_KEY or "").strip()
            if key and not key.startswith(_GEMINI_KEY_PREFIX):
                key_format_ok = False
                key_hint = (
                    f"Key starts with '{key[:8]}...' — expected 'AIzaSy...'. "
                    "This is NOT a Google AI Studio key."
                )
        elif name == "openai":
            key = (settings.OPENAI_API_KEY or "").strip()
            if key and not key.startswith(_OPENAI_KEY_PREFIX):
                key_format_ok = False
                key_hint = f"Key starts with '{key[:8]}...' — expected 'sk-...'."
        elif name == "anthropic":
            key = (settings.ANTHROPIC_API_KEY or "").strip()
            if key and not key.startswith(_ANTHROPIC_KEY_PREFIX):
                key_format_ok = False
                key_hint = f"Key starts with '{key[:8]}...' — expected 'sk-ant-...'."

        if not configured:
            status = "not_configured"
        elif not key_format_ok:
            status = "invalid_key_format"
        elif not health["healthy"]:
            status = f"unhealthy ({health['error_type']})"
        else:
            status = "ready"

        providers[name] = {
            "status":        status,
            "configured":    configured,
            "key_format_ok": key_format_ok,
            "healthy":       health["healthy"],
            "error_type":    health.get("error_type"),
            "key_hint":      key_hint,
            "fix":           _PROVIDER_FIX[name] if status != "ready" else None,
        }

    chain = get_ordered_provider_chain()
    chain_names = [n for n, _ in chain]

    overall = "ok" if chain_names else "degraded"
    message = (
        f"Active provider chain: {chain_names}" if chain_names
        else
        "NO providers ready — every chat query will fall back to chunk display. "
        "Configure at least one provider using the 'fix' instructions below."
    )

    # ── Reranker status ───────────────────────────────────────────────────────
    reranker_status: dict = {
        "enabled":   settings.RERANKER_ENABLED,
        "backend":   settings.RERANKER_BACKEND,
        "model":     settings.RERANKER_MODEL,
        "min_score": settings.RERANKER_MIN_SCORE,
        "min_results": settings.RERANKER_MIN_RESULTS,
        "gap_prune": settings.RERANKER_SCORE_GAP_PRUNE,
        "gap_threshold": settings.RERANKER_SCORE_GAP_THRESHOLD,
        "cohere_key_set": bool((settings.COHERE_API_KEY or "").strip()),
        "jina_key_set":   bool((settings.JINA_API_KEY   or "").strip()),
    }

    backend = (settings.RERANKER_BACKEND or "local").lower()
    if backend == "cohere" and not reranker_status["cohere_key_set"]:
        reranker_status["warning"] = (
            "RERANKER_BACKEND=cohere but COHERE_API_KEY is not set. "
            "Reranker will fall through to local model or bi-encoder order."
        )
    elif backend == "jina" and not reranker_status["jina_key_set"]:
        reranker_status["warning"] = (
            "RERANKER_BACKEND=jina but JINA_API_KEY is not set. "
            "Reranker will fall through to local model or bi-encoder order."
        )

    return {
        "overall":       overall,
        "message":       message,
        "active_chain":  chain_names,
        "primary":       settings.AI_PROVIDER,
        "providers":     providers,
        "model_config": {
            "gemini":    settings.GEMINI_MODEL,
            "openai":    settings.OPENAI_MODEL,
            "anthropic": settings.ANTHROPIC_MODEL,
            "local":     settings.LOCAL_MODEL_NAME,
        },
        "reranker": reranker_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/confidence-gate
# Show the current confidence gate configuration and simulate it against
# a set of example score profiles so you can validate thresholds without
# running a real query.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/confidence-gate")
async def confidence_gate_config(
    user_id: uuid.UUID = Depends(get_current_user),
):
    """
    Return the current confidence gate settings and simulate the gate
    against six representative score profiles to verify the thresholds
    behave as expected.
    """
    from app.services.chat_service import _retrieval_confidence_gate, _calculate_confidence
    from app.models.document import DocumentChunk, Document as _Doc

    # ── Simulate with synthetic (chunk, doc, dist) triples ────────────────────
    # We only need the dist value; chunk/doc are not read by the gate functions.
    _fake = type("_F", (), {})()  # tiny stub — field access not needed

    def _sim_rows(sims: list[float]) -> list[tuple]:
        return [(_fake, _fake, round(1.0 - s, 6)) for s in sims]

    profiles = {
        "direct_answer":       [0.82, 0.74, 0.61, 0.55, 0.40],
        "good_retrieval":      [0.65, 0.58, 0.50, 0.42, 0.35],
        "marginal":            [0.38, 0.33, 0.29, 0.27, 0.22],
        "out_of_domain":       [0.22, 0.18, 0.15, 0.12, 0.10],
        "ceo_favourite_color": [0.20, 0.17, 0.14, 0.11, 0.08],
        "borderline":          [0.45, 0.38, 0.30, 0.25, 0.20],
    }

    simulations = {}
    for name, sims in profiles.items():
        rows = _sim_rows(sims)
        cs, cl = _calculate_confidence(rows)
        blocked, reason, scores = _retrieval_confidence_gate(rows, cs)
        simulations[name] = {
            "input_similarities":  sims,
            "composite_score":     cs,
            "confidence_level":    cl,
            "blocked":             blocked,
            "gate_reason":         reason or "—",
            "score_details":       scores,
        }

    return {
        "gate_enabled": settings.CONFIDENCE_GATE_ENABLED,
        "thresholds": {
            "G1_absolute_min":       settings.CONFIDENCE_GATE_ABSOLUTE_MIN,
            "G2_score_min":          settings.CONFIDENCE_GATE_SCORE_MIN,
            "G3_high_quality_sim":   settings.CONFIDENCE_GATE_HIGH_QUALITY_SIM,
            "G3_marginal_best_sim":  0.40,
        },
        "threshold_guide": {
            "best_sim_0.00_0.25": "G1 fires — absolute noise, blocked",
            "best_sim_0.25_0.40": "borderline — G2 or G3 may fire depending on composite",
            "best_sim_0.40_0.65": "moderate — proceed if composite >= G2 threshold",
            "best_sim_0.65_1.00": "strong signal — always proceed",
        },
        "simulations": simulations,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/health/llm  —  simple LLM liveness check
# Returns which provider is active, whether the key is present and valid-format,
# and whether the last generation attempt succeeded.
# Also registered as GET /health/llm for convenience.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health/llm", include_in_schema=True)
async def llm_health(
    user_id: uuid.UUID = Depends(get_current_user),
):
    """
    Quick LLM health check.

    Returns current provider status, key presence, and whether the last
    generation attempt succeeded.  No LLM call is made.

    Example response (healthy):
        {"provider": "gemini", "status": "healthy", "model": "gemini-2.5-flash",
         "api_key_present": true, "last_error": null, "last_response_ms": 2341}

    Example response (degraded):
        {"provider": "gemini", "status": "quota_exceeded",
         "model": "gemini-2.5-flash", "api_key_present": true,
         "last_error": "Gemini quota exceeded", "last_response_ms": null,
         "fallback_provider": "openai", "fallback_status": "healthy"}
    """
    from app.ai_providers import (
        get_provider_health,
        get_ordered_provider_chain,
        get_llm_diagnostics,
        _is_provider_configured,
    )

    primary       = settings.AI_PROVIDER
    primary_health = get_provider_health(primary)
    primary_key    = (getattr(settings, f"{primary.upper()}_API_KEY", "") or "").strip()
    diag           = get_llm_diagnostics()

    # Determine overall status string
    if not _is_provider_configured(primary):
        status = "not_configured"
    elif not primary_health["healthy"]:
        status = primary_health["error_type"] or "unhealthy"
    else:
        status = "healthy"

    # Active model name
    _model_map = {
        "gemini":    settings.GEMINI_MODEL,
        "openai":    settings.OPENAI_MODEL,
        "anthropic": settings.ANTHROPIC_MODEL,
        "local":     settings.LOCAL_MODEL_NAME,
    }

    # Fallback provider info
    chain      = get_ordered_provider_chain()
    chain_names = [n for n, _ in chain]
    fallback   = next((n for n in chain_names if n != primary), None)
    fallback_health = get_provider_health(fallback) if fallback else None

    return {
        "provider":          primary,
        "status":            status,
        "model":             _model_map.get(primary, "unknown"),
        "api_key_present":   bool(primary_key),
        "active_chain":      chain_names,
        "last_error":        diag["last_error"],
        "last_error_type":   diag["last_error_type"],
        "last_response_ms":  diag["last_response_ms"],
        "total_requests":    diag["total_requests"],
        "total_failures":    diag["total_failures"],
        "fallback_provider": fallback,
        "fallback_status":   (
            fallback_health["error_type"] or "healthy"
            if fallback_health and not fallback_health["healthy"]
            else "healthy" if fallback else None
        ),
        "fix": (
            None if status == "healthy"
            else _PROVIDER_FIX.get(primary, "Check backend/.env and server logs.")
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /debug/llm  —  full LLM diagnostics
# Returns detailed information about every provider, last call stats, and
# actionable fix instructions for each unhealthy provider.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/llm", include_in_schema=True)
async def debug_llm(
    user_id: uuid.UUID = Depends(get_current_user),
):
    """
    Full LLM diagnostics — provider config, health, last call statistics,
    and actionable fix instructions for every configured provider.

    Useful for diagnosing "Answer generation is temporarily unavailable" errors.
    """
    import time as _t
    from app.ai_providers import (
        get_provider_health,
        get_ordered_provider_chain,
        get_llm_diagnostics,
        _is_provider_configured,
    )

    diag        = get_llm_diagnostics()
    chain       = get_ordered_provider_chain()
    chain_names = [n for n, _ in chain]
    primary     = settings.AI_PROVIDER

    _model_map = {
        "gemini":    settings.GEMINI_MODEL,
        "openai":    settings.OPENAI_MODEL,
        "anthropic": settings.ANTHROPIC_MODEL,
        "local":     settings.LOCAL_MODEL_NAME,
    }
    _key_map = {
        "gemini":    (settings.GEMINI_API_KEY    or "").strip(),
        "openai":    (settings.OPENAI_API_KEY    or "").strip(),
        "anthropic": (settings.ANTHROPIC_API_KEY or "").strip(),
        "local":     (settings.LOCAL_MODEL_ENDPOINT or "").strip(),
    }

    all_providers: dict = {}
    for name in ["gemini", "openai", "anthropic", "local"]:
        configured = _is_provider_configured(name)
        health     = get_provider_health(name)
        key        = _key_map[name]

        # Format key hint (never expose key value, only first chars)
        key_hint = None
        if key:
            key_hint = f"{key[:8]}..." if len(key) > 8 else "(set)"
        if name == "gemini" and key and not key.startswith(_GEMINI_KEY_PREFIX):
            key_hint = (
                f"{key[:8]}... — WRONG FORMAT (expected 'AIzaSy...'). "
                "This is not a Google AI Studio key."
            )
        elif name == "openai" and key and not key.startswith(_OPENAI_KEY_PREFIX):
            key_hint = (
                f"{key[:8]}... — WRONG FORMAT (expected 'sk-...')."
            )
        elif name == "anthropic" and key and not key.startswith(_ANTHROPIC_KEY_PREFIX):
            key_hint = (
                f"{key[:8]}... — WRONG FORMAT (expected 'sk-ant-...')."
            )

        if not configured:
            status = "not_configured"
        elif not health["healthy"]:
            status = health["error_type"] or "unhealthy"
        else:
            status = "healthy"

        # Health TTL remaining
        ttl_remaining = None
        from app.ai_providers import _health_cache
        hentry = _health_cache.get(name)
        if hentry and not hentry.get("healthy", True):
            age    = _t.monotonic() - hentry.get("checked_at", 0)
            ttl    = hentry.get("ttl", settings.PROVIDER_HEALTH_TTL)
            remaining = max(0, ttl - age)
            ttl_remaining = round(remaining)

        all_providers[name] = {
            "status":        status,
            "configured":    configured,
            "model":         _model_map[name],
            "key_hint":      key_hint,
            "healthy":       health["healthy"],
            "error_type":    health["error_type"],
            "ttl_remaining_s": ttl_remaining,
            "in_active_chain": name in chain_names,
            "fix":           _PROVIDER_FIX.get(name) if status != "healthy" else None,
        }

    # Last call stats (human-readable timestamps)
    last_error_ago = None
    if diag["last_error_at"]:
        last_error_ago = round(_t.time() - diag["last_error_at"])

    return {
        "summary": {
            "primary_provider":   primary,
            "active_chain":       chain_names,
            "chain_healthy":      bool(chain_names),
            "total_requests":     diag["total_requests"],
            "total_failures":     diag["total_failures"],
            "failure_rate_pct": (
                round(100 * diag["total_failures"] / diag["total_requests"], 1)
                if diag["total_requests"] > 0
                else 0
            ),
            "diagnosis": (
                f"OK — active chain: {chain_names}"
                if chain_names
                else (
                    "CRITICAL — no providers in chain. "
                    "Every chat query falls back to document excerpt display. "
                    "Configure at least one provider (see 'providers' below)."
                )
            ),
        },
        "last_call": {
            "provider":       diag["last_provider"],
            "model":          diag["last_model"],
            "input_chars":    diag["last_input_chars"],
            "input_tokens_approx": (
                diag["last_input_chars"] // 4
                if diag["last_input_chars"] is not None else None
            ),
            "response_chars": diag["last_response_chars"],
            "response_tokens_approx": (
                diag["last_response_chars"] // 4
                if diag["last_response_chars"] is not None else None
            ),
            "response_ms":    diag["last_response_ms"],
        },
        "last_error": {
            "provider":     diag["last_error_provider"],
            "error_type":   diag["last_error_type"],
            "detail":       diag["last_error"],
            "seconds_ago":  last_error_ago,
            "human_reason": (
                {
                    "auth_failed":    "API key is invalid or revoked.",
                    "quota_exceeded": "Daily API quota has been reached.",
                    "unavailable":    "Provider is down or connection timed out.",
                    "not_configured": "No API key is set.",
                }.get(diag["last_error_type"] or "", diag["last_error"] or "—")
            ),
        },
        "providers": all_providers,
        "config": {
            "PROVIDER_HEALTH_TTL":  settings.PROVIDER_HEALTH_TTL,
            "PROVIDER_QUOTA_TTL":   settings.PROVIDER_QUOTA_TTL,
            "note_quota_ttl": (
                f"A quota-exceeded provider is skipped for {settings.PROVIDER_QUOTA_TTL}s "
                f"({settings.PROVIDER_QUOTA_TTL // 3600}h) before being retried. "
                "Server restart clears this."
            ),
        },
    }
