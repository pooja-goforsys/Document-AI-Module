import uuid
from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as UUIDType, JSONB
from app.core.database import Base


class QueryAnalytics(Base):
    """Per-query retrieval debug record. Written asynchronously after each response."""

    __tablename__ = "query_analytics"

    id         = Column(UUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUIDType(as_uuid=True), nullable=False, index=True)
    session_id = Column(UUIDType(as_uuid=True), nullable=True,  index=True)

    original_query  = Column(Text,        nullable=False)
    expanded_query  = Column(Text,        nullable=True)   # after contextualization
    response_mode   = Column(String(20),  nullable=True)
    scope_type      = Column(String(20),  nullable=True)

    chunks_retrieved  = Column(Integer, nullable=True)   # total after merge + dedup
    docs_searched     = Column(Integer, nullable=True)   # distinct documents
    confidence_score  = Column(Float,   nullable=True)   # 0–100
    response_time_ms  = Column(Integer, nullable=True)   # wall-clock ms

    entities_extracted = Column(JSONB, nullable=True)    # list[str]
    # [{doc_name, page, dist, sim}] — top-5 chunks after re-ranking
    top_chunks         = Column(JSONB, nullable=True)

    used_pgvector      = Column(String(10), nullable=True)  # "yes" | "no"

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
