import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.document import Document, DocumentStatus
from app.models.folder import Folder
from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.schemas.document import StatsResponse
from app.schemas.chat import RecentQueryResponse
from app.services import chat_service

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(timezone.utc).date()

    total_docs = await db.scalar(
        select(func.count(Document.id)).where(Document.user_id == user_id)
    )
    total_folders = await db.scalar(
        select(func.count(Folder.id)).where(Folder.user_id == user_id)
    )
    indexed_docs = await db.scalar(
        select(func.count(Document.id))
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
    )
    queries_today = await db.scalar(
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .where(ChatMessage.role == MessageRole.user.value)
        .where(cast(ChatMessage.created_at, Date) == today)
    )
    storage_bytes = await db.scalar(
        select(func.coalesce(func.sum(Document.file_size), 0))
        .where(Document.user_id == user_id)
    )

    return StatsResponse(
        total_documents=total_docs or 0,
        total_folders=total_folders or 0,
        indexed_documents=indexed_docs or 0,
        ai_queries_today=queries_today or 0,
        storage_used_mb=round((storage_bytes or 0) / (1024 * 1024), 2),
    )


@router.get("/queries/recent", response_model=list[RecentQueryResponse])
async def get_recent_queries(
    limit: int = Query(10, ge=1, le=50),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await chat_service.get_recent_queries(user_id, db, limit)
