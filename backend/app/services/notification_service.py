"""
Notification service — Phase 1: PostgreSQL-backed, database-driven.

Architecture is designed for future migration to real-time delivery (WebSockets,
Firebase Cloud Messaging) without changing callers:

  Phase 1 (now):   create_notification() writes to DB only.
  Phase 2 (later): wrap create_notification() with an asyncio.create_task() that
                   pushes the notification via WebSocket or FCM before returning.
                   The DB write remains the source of truth; push is fire-and-forget.

Integration pattern
-------------------
Call `create_notification(user_id, title, message, type, db=db)` from any
in-request handler (document upload, delete, etc.).

Call `create_notification(user_id, title, message, type, db=None)` from background
tasks — a new session is opened internally and committed before returning.

Failures are swallowed with a warning log so a notification hiccup never
breaks the main operation.
"""
import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from app.models.notification import Notification
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    UnreadCountResponse,
)
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ─── Core helper ──────────────────────────────────────────────────────────────

async def create_notification(
    user_id: uuid.UUID,
    title: str,
    message: str,
    notification_type: str = "system",
    db: AsyncSession | None = None,
) -> Notification | None:
    """
    Create a notification and persist it.

    Pass db= for in-request code (session is committed by get_db at request end).
    Pass db=None for background tasks (opens own session, commits immediately).
    Never raises — failures are logged as warnings.
    """
    async def _insert(session: AsyncSession) -> Notification:
        notif = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=notification_type,
        )
        session.add(notif)
        await session.flush()
        await session.refresh(notif)
        return notif

    try:
        if db is not None:
            return await _insert(db)

        async with AsyncSessionLocal() as session:
            result = await _insert(session)
            await session.commit()
            return result

    except Exception as exc:
        if db is not None:
            try:
                await db.rollback()
            except Exception:
                pass
        logger.warning(f"[Notification] Failed to create notification for user {user_id}: {exc}")
        return None


# ─── Query helpers ─────────────────────────────────────────────────────────────

async def list_notifications(
    user_id: uuid.UUID,
    db: AsyncSession,
    page: int = 1,
    limit: int = 20,
    unread_only: bool = False,
) -> NotificationListResponse:
    offset = (page - 1) * limit
    filters = [Notification.user_id == user_id]
    if unread_only:
        filters.append(Notification.is_read == False)  # noqa: E712

    total = (await db.scalar(
        select(func.count(Notification.id)).where(*filters)
    )) or 0

    unread = (await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )) or 0

    rows = (await db.execute(
        select(Notification)
        .where(*filters)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in rows],
        total=total,
        unread=unread,
    )


async def get_unread_count(user_id: uuid.UUID, db: AsyncSession) -> int:
    return (await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )) or 0


async def mark_as_read(
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> NotificationResponse | None:
    notif = await db.get(Notification, notification_id)
    if not notif or notif.user_id != user_id:
        return None
    notif.is_read = True
    await db.flush()
    await db.refresh(notif)
    return NotificationResponse.model_validate(notif)


async def mark_all_as_read(user_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
        .execution_options(synchronize_session="fetch")
    )
    return result.rowcount


async def delete_notification(
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    notif = await db.get(Notification, notification_id)
    if not notif or notif.user_id != user_id:
        return False
    await db.delete(notif)
    return True
