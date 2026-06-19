import uuid
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as UUIDType
from app.core.database import Base


class SavedPrompt(Base):
    __tablename__ = "saved_prompts"

    id = Column(UUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUIDType(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title       = Column(String(200), nullable=False)
    content     = Column(Text,        nullable=False)
    # Optional hints stored with the prompt
    response_mode = Column(String(20),  nullable=True)   # auto | simple | detailed | …
    category      = Column(String(100), nullable=True)   # Summary | Analysis | Custom …

    use_count  = Column(Integer,  nullable=False, default=0)
    is_pinned  = Column(Boolean,  nullable=False, default=False)  # floats to top of list

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
