import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class SavedPromptCreate(BaseModel):
    title:         str             = Field(..., min_length=1, max_length=200)
    content:       str             = Field(..., min_length=1)
    response_mode: str | None      = None
    category:      str | None      = None


class SavedPromptUpdate(BaseModel):
    title:         str | None      = Field(None, min_length=1, max_length=200)
    content:       str | None      = None
    response_mode: str | None      = None
    category:      str | None      = None
    is_pinned:     bool | None     = None


class SavedPromptResponse(BaseModel):
    id:            uuid.UUID
    title:         str
    content:       str
    response_mode: str | None
    category:      str | None
    use_count:     int
    is_pinned:     bool
    created_at:    datetime
    updated_at:    datetime

    class Config:
        from_attributes = True
