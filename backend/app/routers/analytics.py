"""
Retrieval analytics endpoint.

Returns the last N query records for the current user, including
chunks_retrieved, confidence_score, response_time_ms, and top_chunks
debug data.  Useful for monitoring retrieval quality and diagnosing
missed answers.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime
import uuid

from app.core.deps import get_current_user, get_db
from app.models.analytics import QueryAnalytics

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class QueryAnalyticsResponse(BaseModel):
    id:                 uuid.UUID
    session_id:         uuid.UUID | None
    original_query:     str
    expanded_query:     str | None
    response_mode:      str | None
    scope_type:         str | None
    chunks_retrieved:   int | None
    docs_searched:      int | None
    confidence_score:   float | None
    response_time_ms:   int | None
    entities_extracted: list[str] | None
    top_chunks:         list[dict] | None
    used_pgvector:      str | None
    created_at:         datetime

    class Config:
        from_attributes = True


class RagMetricsResponse(BaseModel):
    query_count: int
    retrieval_accuracy_proxy: float
    answer_accuracy_proxy: float
    citation_accuracy_proxy: float
    hallucination_rate_proxy: float
    average_retrieval_score: float
    chunk_relevance_score: float
    average_latency_ms: int


@router.get("/queries", response_model=list[QueryAnalyticsResponse])
async def get_query_analytics(
    limit: int         = Query(50, ge=1, le=200),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    """Return the most recent retrieval analytics records for the current user."""
    stmt = (
        select(QueryAnalytics)
        .where(QueryAnalytics.user_id == user_id)
        .order_by(QueryAnalytics.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/rag-metrics", response_model=RagMetricsResponse)
async def get_rag_metrics(
    limit: int = Query(500, ge=1, le=5000),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregate RAG quality metrics from recent query analytics."""
    stmt = (
        select(QueryAnalytics)
        .where(QueryAnalytics.user_id == user_id)
        .order_by(QueryAnalytics.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return RagMetricsResponse(
            query_count=0,
            retrieval_accuracy_proxy=0.0,
            answer_accuracy_proxy=0.0,
            citation_accuracy_proxy=0.0,
            hallucination_rate_proxy=0.0,
            average_retrieval_score=0.0,
            chunk_relevance_score=0.0,
            average_latency_ms=0,
        )

    confidence_scores = [float(r.confidence_score or 0.0) for r in rows]
    top_chunk_scores: list[float] = []
    cited_queries = 0
    for row in rows:
        chunks = row.top_chunks or []
        if chunks:
            cited_queries += 1
        for chunk in chunks:
            try:
                top_chunk_scores.append(float(chunk.get("sim", 0.0)))
            except Exception:
                continue

    avg_conf = sum(confidence_scores) / len(confidence_scores)
    avg_chunk = sum(top_chunk_scores) / len(top_chunk_scores) if top_chunk_scores else 0.0
    citation_rate = cited_queries / len(rows)
    high_conf_rate = sum(1 for score in confidence_scores if score >= 60.0) / len(rows)
    low_conf_rate = sum(1 for score in confidence_scores if score < 35.0) / len(rows)
    avg_latency = int(sum(int(r.response_time_ms or 0) for r in rows) / len(rows))

    return RagMetricsResponse(
        query_count=len(rows),
        retrieval_accuracy_proxy=round(high_conf_rate * 100, 2),
        answer_accuracy_proxy=round(avg_conf, 2),
        citation_accuracy_proxy=round(citation_rate * 100, 2),
        hallucination_rate_proxy=round(low_conf_rate * 100, 2),
        average_retrieval_score=round(avg_chunk, 4),
        chunk_relevance_score=round(avg_chunk * 100, 2),
        average_latency_ms=avg_latency,
    )
