from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid


class DocumentResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str              # = original_name
    type: str              # = file_type
    size: int              # = file_size
    folder_id: Optional[uuid.UUID]
    folder_name: Optional[str]
    status: str
    chunk_count: int
    page_count: Optional[int]
    indexed: bool          # True if status == "indexed"
    uploaded_at: datetime
    indexed_at: Optional[datetime]
    summary: Optional[str] = None


class DocumentUpdate(BaseModel):
    """PATCH /documents/{id} — all fields optional; omitted = unchanged.
    Send folder_id=null explicitly to move a document out of its folder."""
    name: Optional[str] = None
    folder_id: Optional[str] = None   # None kept as sentinel; use model_fields_set


class UploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    message: str
    status: str


class SummarizeRequest(BaseModel):
    scope: str = "full"   # "full" | "executive" | "key_takeaways"


class SummarizeResponse(BaseModel):
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    folder_id: Optional[str] = None
    folder_name: Optional[str] = None
    scope: str
    summary: str


class StatsResponse(BaseModel):
    total_documents: int
    total_folders: int
    indexed_documents: int
    ai_queries_today: int
    storage_used_mb: float
    storage_total_mb: float = 10240.0
