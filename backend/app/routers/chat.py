import uuid
import asyncio
import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.chat import (
    ChatQueryRequest,
    ChatSessionResponse,
    ChatMessageResponse,
    SessionUpdate,
    FeedbackRequest,
    FeedbackResponse,
)
from app.services import chat_service
from app.core.exceptions import NotFoundError

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _safe_stream(
    request: ChatQueryRequest,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    logger.info(
        "[STREAM] Streaming started user_id=%s session_id=%s question=%r",
        user_id,
        request.session_id,
        request.question,
    )
    try:
        async for chunk in chat_service.stream_query(request, user_id, db):
            yield chunk
        logger.info(
            "[STREAM] Streaming completed user_id=%s session_id=%s",
            user_id,
            request.session_id,
        )
    except (GeneratorExit, asyncio.CancelledError, ConnectionResetError) as exc:
        logger.warning("[ChatStream] client disconnected: %s", type(exc).__name__)
        raise
    except TimeoutError as exc:
        logger.error("[ChatStream] timeout while streaming response", exc_info=True)
        yield _sse("error", {"message": "The response timed out while streaming.", "error_type": "timeout"})
        yield _sse("done", {"session_id": str(request.session_id) if request.session_id else None})
    except Exception as exc:
        logger.error("[ChatStream] generator crashed after stream started", exc_info=True)
        yield _sse("error", {
            "message": "The chat stream failed on the server. Check server logs.",
            "error_type": type(exc).__name__,
        })
        yield _sse("done", {"session_id": str(request.session_id) if request.session_id else None})


async def _safe_regenerate_stream(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    logger.info("[STREAM] Regenerate streaming started user_id=%s session_id=%s", user_id, session_id)
    try:
        async for chunk in chat_service.regenerate_response(session_id, user_id, db):
            yield chunk
        logger.info("[STREAM] Regenerate streaming completed user_id=%s session_id=%s", user_id, session_id)
    except (GeneratorExit, asyncio.CancelledError, ConnectionResetError) as exc:
        logger.warning("[ChatStream] regenerate client disconnected: %s", type(exc).__name__)
        raise
    except TimeoutError:
        logger.error("[ChatStream] timeout while regenerating response", exc_info=True)
        yield _sse("error", {"message": "The response timed out while streaming.", "error_type": "timeout"})
        yield _sse("done", {"session_id": str(session_id)})
    except Exception as exc:
        logger.error("[ChatStream] regenerate generator crashed after stream started", exc_info=True)
        yield _sse("error", {
            "message": "The chat stream failed on the server. Check server logs.",
            "error_type": type(exc).__name__,
        })
        yield _sse("done", {"session_id": str(session_id)})


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await chat_service.list_sessions(user_id, db)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_session(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.ensure_session(None, user_id, db)
    await db.commit()
    await db.refresh(session)
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        pinned=session.pinned,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.chat import ChatSession, ChatMessage
    from sqlalchemy import select, func
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")
    msg_count = await db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        scope_type=session.scope_type,
        scope_id=session.scope_id,
        scope_name=session.scope_name,
        pinned=session.pinned,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=msg_count or 0,
    )


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update session title and/or pinned state (PATCH — only provided fields change)."""
    return await chat_service.update_session(
        session_id,
        user_id,
        title=body.title,
        pinned=body.pinned,
        db=db,
    )


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await chat_service.get_session_messages(session_id, user_id, db)


@router.post("/sessions/{session_id}/query")
async def stream_query(
    session_id: uuid.UUID,
    request: ChatQueryRequest,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request.session_id = session_id
    logger.info(
        "[CHAT] Request received endpoint=/chat/sessions/{session_id}/query "
        "user_id=%s session_id=%s payload=%s",
        user_id,
        session_id,
        request.model_dump(mode="json"),
    )
    return StreamingResponse(
        _safe_stream(request, user_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/query")
async def stream_query_new_session(
    request: ChatQueryRequest,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new session automatically when no session_id is provided."""
    logger.info(
        "[CHAT] Request received endpoint=/chat/query user_id=%s payload=%s",
        user_id,
        request.model_dump(mode="json"),
    )
    return StreamingResponse(
        _safe_stream(request, user_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_service.delete_session(session_id, user_id, db)


@router.post(
    "/messages/{message_id}/feedback",
    response_model=FeedbackResponse,
    status_code=201,
)
async def submit_feedback(
    message_id: uuid.UUID,
    body: FeedbackRequest,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit like/dislike feedback for an assistant message.

    Calling this endpoint again with a different rating replaces the existing
    feedback (upsert semantics).
    The session_id is resolved from the message itself.
    """
    from app.models.chat import ChatMessage, ChatSession
    msg = await db.get(ChatMessage, message_id)
    if not msg:
        raise NotFoundError("Message")
    # Verify the message belongs to a session owned by the current user before
    # passing it to the service.  Using NotFoundError (not 403) intentionally
    # so we don't confirm whether the message_id exists for another user.
    session = await db.get(ChatSession, msg.session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Message")

    return await chat_service.submit_feedback(
        message_id=message_id,
        session_id=msg.session_id,
        user_id=user_id,
        rating=body.rating,
        db=db,
    )


@router.post("/sessions/{session_id}/regenerate")
async def regenerate_response(
    session_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the last assistant message and regenerate it from the last user question."""
    return StreamingResponse(
        _safe_regenerate_stream(session_id, user_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
