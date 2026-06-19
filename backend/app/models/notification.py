import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class NotificationType(str, enum.Enum):
    document = "document"
    ai       = "ai"
    error    = "error"
    system   = "system"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str]   = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # "document" | "ai" | "error" | "system"
    type: Mapped[str]     = mapped_column(String(20), default=NotificationType.system.value, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")

    __table_args__ = (
        # Composite index: most common query is "unread for user X, newest first"
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )
