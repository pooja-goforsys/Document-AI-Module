from pydantic import BaseModel, field_validator
from datetime import datetime
import uuid


class FolderCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Folder name cannot be empty.")
        if len(v) > 255:
            raise ValueError("Folder name too long (max 255 chars).")
        return v


class FolderRename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Folder name cannot be empty.")
        return v


class FolderResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    document_count: int = 0
    created_at: datetime
    updated_at: datetime
