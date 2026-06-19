import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, BigInteger, DateTime, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class DocumentStatus(str, enum.Enum):
    pending   = "pending"
    indexing  = "indexing"
    indexed   = "indexed"
    failed    = "failed"


class FileType(str, enum.Enum):
    pdf  = "pdf"
    docx = "docx"
    txt  = "txt"
    xlsx = "xlsx"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID]             = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_name: Mapped[str]        = mapped_column(String(500), nullable=False)
    stored_name: Mapped[str]          = mapped_column(String(500), nullable=False)
    file_type: Mapped[str]            = mapped_column(String(20), nullable=False)
    file_size: Mapped[int]            = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int | None]    = mapped_column(Integer, nullable=True)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str]               = mapped_column(String(20), default=DocumentStatus.pending, nullable=False)
    chunk_count: Mapped[int]          = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Enterprise: AI-generated document summary (populated after indexing)
    summary: Mapped[str | None]       = mapped_column(Text, nullable=True)
    # Knowledge domain (populated after indexing via domain classifier)
    domain_name: Mapped[str | None]   = mapped_column(String(200), nullable=True)
    uploaded_at: Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user   = relationship("User",           back_populates="documents")
    folder = relationship("Folder",         back_populates="documents")
    chunks = relationship("DocumentChunk",  back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int]  = mapped_column(Integer, nullable=False)
    content: Mapped[str]      = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Section heading extracted during parsing — used for metadata filtering in retrieval
    section_heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source_document: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extraction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Native PostgreSQL ARRAY — no pgvector extension required
    embedding               = mapped_column(ARRAY(Float), nullable=True)

    document = relationship("Document", back_populates="chunks")
