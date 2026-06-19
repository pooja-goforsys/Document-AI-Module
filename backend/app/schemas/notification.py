from pydantic import BaseModel
from datetime import datetime
import uuid


class NotificationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    message: str
    type: str
    is_read: bool
    created_at: datetime


class UnreadCountResponse(BaseModel):
    count: int


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread: int
