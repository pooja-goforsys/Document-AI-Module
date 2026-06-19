import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import NotFoundError
from app.schemas.notification import (
    NotificationResponse,
    UnreadCountResponse,
    NotificationListResponse,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.list_notifications(user_id, db, page, limit, unread_only)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await notification_service.get_unread_count(user_id, db)
    return UnreadCountResponse(count=count)


# read-all MUST be defined before /{notification_id}/read to avoid routing
# ambiguity — FastAPI matches routes in order for same-method+prefix patterns.
@router.patch("/read-all")
async def mark_all_read(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await notification_service.mark_all_as_read(user_id, db)
    return {"marked_read": count}


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await notification_service.mark_as_read(notification_id, user_id, db)
    if not result:
        raise NotFoundError("Notification")
    return result


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await notification_service.delete_notification(notification_id, user_id, db)
    if not deleted:
        raise NotFoundError("Notification")
