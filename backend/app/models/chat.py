import uuid
from datetime import datetime
from sqlalchemy import String, Text, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class MessageRole(str, enum.Enum):
    user      = "user"
    assistant = "assistant"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str]     = mapped_column(String(500), default="New Chat", nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Scope: which documents to search — 'all' | 'folder' | 'document'
    scope_type: Mapped[str]              = mapped_column(String(20), default="all", nullable=False)
    scope_id: Mapped[uuid.UUID | None]   = mapped_column(UUID(as_uuid=True), nullable=True)
    scope_name: Mapped[str | None]       = mapped_column(String(500), nullable=True)

    # Enterprise: pinned sessions float to the top of the list
    pinned: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user      = relationship("User",            back_populates="chat_sessions")
    messages  = relationship("ChatMessage",     back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")
    feedbacks = relationship("MessageFeedback", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID]  = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str]      = mapped_column(String(20), nullable=False)
    content: Mapped[str]   = mapped_column(Text, nullable=False)
    # [{"document_id": "...", "document_name": "...", "page_number": 3, "score": 0.92}]
    sources                = mapped_column(JSONB, default=list, nullable=False)
    # Retrieval-based confidence: 0–100, null for user messages
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Enterprise: response mode used when generating this message
    response_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session   = relationship("ChatSession",    back_populates="messages")
    feedbacks = relationship("MessageFeedback", back_populates="message", cascade="all, delete-orphan")


class MessageFeedback(Base):
    __tablename__ = "message_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id",          ondelete="CASCADE"), nullable=False)
    rating: Mapped[str]           = mapped_column(String(10), nullable=False)   # 'like' | 'dislike'
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=func.now())

    message = relationship("ChatMessage", back_populates="feedbacks")
    session = relationship("ChatSession", back_populates="feedbacks")
