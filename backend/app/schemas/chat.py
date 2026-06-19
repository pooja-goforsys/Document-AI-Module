from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Literal, Optional
import uuid


class SourceCitation(BaseModel):
    document_id: uuid.UUID
    document_name: str
    page_number: Optional[int]
    score: float            # cosine similarity 0–1
    domain_name: Optional[str] = None
    chunk_id: Optional[uuid.UUID] = None
    highlight_text: Optional[str] = None


class ChatQueryRequest(BaseModel):
    question: str
    session_id: Optional[uuid.UUID] = None   # None → create new session

    # Scope: which documents to search in this session
    scope_type: Literal["all", "folder", "document", "domain"] = "all"
    scope_id:   Optional[uuid.UUID] = None   # folder_id or document_id (None for domain scope)
    scope_name: Optional[str]       = None   # display label / domain name

    # Enterprise: response mode controls answer style
    response_mode: Literal[
        "auto",
        "simple",
        "detailed",
        "technical",
        "summary",
        "bullets",
        "executive",
    ] = "auto"

    # When True, skip document disambiguation and answer from all matching docs
    bypass_disambiguation: bool = False

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question cannot be empty.")
        if len(v) > 4000:
            raise ValueError("Question is too long (max 4000 characters).")
        return v


class ChatMessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    role: str
    content: str
    sources: list[SourceCitation] = []
    confidence_score: Optional[float] = None
    response_mode: Optional[str] = None
    created_at: datetime


class ChatSessionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    scope_type: str = "all"
    scope_id:   Optional[uuid.UUID] = None
    scope_name: Optional[str]       = None
    pinned: bool = False
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message_preview: Optional[str] = None


class ChatQueryResponse(BaseModel):
    success: bool
    session_id: uuid.UUID
    answer: str
    sources: list[SourceCitation]
    message: str = ""


class RecentQueryResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    question: str
    sources: list[SourceCitation]
    created_at: datetime
    answer_preview: Optional[str] = None


class SessionUpdate(BaseModel):
    """PATCH /chat/sessions/{id} — update title and/or pinned state."""
    title:  Optional[str]  = None
    pinned: Optional[bool] = None


class FeedbackRequest(BaseModel):
    rating: Literal["like", "dislike"]


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    message_id: uuid.UUID
    rating: str
    created_at: datetime
