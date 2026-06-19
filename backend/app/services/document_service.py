import os
import uuid
import aiofiles
from fastapi import UploadFile, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.folder import Folder
from app.schemas.document import DocumentResponse, DocumentUpdate
from app.utils.file_utils import get_file_type, safe_filename, validate_file_size, get_upload_path
from app.core.config import settings
from app.tasks.indexing_task import run_indexing_task
from app.services.notification_service import create_notification
import asyncio


def _doc_to_response(doc: Document, folder_name: str | None = None) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        name=doc.original_name,
        type=doc.file_type,
        size=doc.file_size,
        folder_id=doc.folder_id,
        folder_name=folder_name,
        status=doc.status,
        chunk_count=doc.chunk_count,
        page_count=doc.page_count,
        indexed=doc.status == DocumentStatus.indexed,
        uploaded_at=doc.uploaded_at,
        indexed_at=doc.indexed_at,
        summary=doc.summary,
    )


async def upload_and_index(
    file: UploadFile,
    folder_id: str | None,
    user_id: uuid.UUID,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> DocumentResponse:
    # Validate
    content = await file.read()
    size    = len(content)
    validate_file_size(size)
    file_type    = get_file_type(file.filename or "unknown")
    stored_name  = safe_filename(file.filename or "document")
    file_path    = get_upload_path(stored_name)

    # Validate folder ownership
    resolved_folder_id = None
    folder_name        = None
    if folder_id:
        fid = uuid.UUID(folder_id)
        row = await db.get(Folder, fid)
        if row and row.user_id == user_id:
            resolved_folder_id = fid
            folder_name        = row.name

    # Persist file
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Create DB record
    doc = Document(
        original_name=file.filename,
        stored_name=stored_name,
        file_type=file_type,
        file_size=size,
        folder_id=resolved_folder_id,
        user_id=user_id,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Notification: document uploaded (isolated session — keeps request session clean)
    await create_notification(
        user_id=user_id,
        title="Document uploaded",
        message=f"'{doc.original_name}' was uploaded successfully and is being indexed.",
        notification_type="document",
        db=None,
    )

    # Kick off background indexing
    background_tasks.add_task(run_indexing_task, doc.id, file_path, file_type, user_id)

    return _doc_to_response(doc, folder_name)


async def list_documents(
    user_id: uuid.UUID,
    folder_id: str | None,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
) -> list[DocumentResponse]:
    stmt = (
        select(Document, Folder.name.label("folder_name"))
        .outerjoin(Folder, Document.folder_id == Folder.id)
        .where(Document.user_id == user_id)
        .order_by(Document.uploaded_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if folder_id:
        try:
            stmt = stmt.where(Document.folder_id == uuid.UUID(folder_id))
        except (ValueError, AttributeError):
            pass  # ignore invalid folder_id, return all docs

    rows = await db.execute(stmt)
    results = rows.all()
    return [_doc_to_response(doc, fname) for doc, fname in results]


async def get_document(doc_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> DocumentResponse:
    from app.core.exceptions import NotFoundError
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")
    fname = None
    if doc.folder_id:
        folder = await db.get(Folder, doc.folder_id)
        fname  = folder.name if folder else None
    return _doc_to_response(doc, fname)


async def delete_document(doc_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    from app.core.exceptions import NotFoundError
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")
    doc_name  = doc.original_name  # capture before deletion
    file_path = get_upload_path(doc.stored_name)
    await db.delete(doc)
    await db.commit()
    # Remove file from disk (best-effort)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        pass
    # Notification: document deleted (own session — main session already committed)
    await create_notification(
        user_id=user_id,
        title="Document deleted",
        message=f"'{doc_name}' has been removed.",
        notification_type="document",
        db=None,
    )


async def reindex_document(doc_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession, background_tasks: BackgroundTasks):
    from app.core.exceptions import NotFoundError
    from sqlalchemy import update
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")
    # Delete existing chunks
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
    # Reset status
    from sqlalchemy import update
    await db.execute(update(Document).where(Document.id == doc_id).values(status=DocumentStatus.pending, chunk_count=0, error_message=None))
    await db.commit()
    file_path = get_upload_path(doc.stored_name)
    background_tasks.add_task(run_indexing_task, doc.id, file_path, doc.file_type, user_id)
    return {"message": "Re-indexing started."}


async def update_document(
    doc_id: uuid.UUID,
    body: DocumentUpdate,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> DocumentResponse:
    """PATCH — rename and/or move a document to a different folder."""
    from app.core.exceptions import NotFoundError
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")

    if "name" in body.model_fields_set and body.name:
        doc.original_name = body.name.strip()

    folder_name: str | None = None
    if "folder_id" in body.model_fields_set:
        if body.folder_id is None:
            doc.folder_id = None          # explicitly move to root
        else:
            try:
                fid = uuid.UUID(body.folder_id)
                folder = await db.get(Folder, fid)
                if folder and folder.user_id == user_id:
                    doc.folder_id = fid
                    folder_name   = folder.name
            except (ValueError, AttributeError):
                pass  # ignore bad UUID

    await db.commit()
    await db.refresh(doc)

    if folder_name is None and doc.folder_id:
        folder = await db.get(Folder, doc.folder_id)
        folder_name = folder.name if folder else None

    return _doc_to_response(doc, folder_name)


async def replace_file(
    doc_id: uuid.UUID,
    file: UploadFile,
    user_id: uuid.UUID,
    db: AsyncSession,
    background_tasks: BackgroundTasks,
) -> DocumentResponse:
    """PUT /{doc_id}/file — swap the stored file and re-index from scratch."""
    from app.core.exceptions import NotFoundError
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")

    content = await file.read()
    validate_file_size(len(content))

    new_file_type   = get_file_type(file.filename or "document")
    new_stored_name = safe_filename(file.filename or "document")
    new_file_path   = get_upload_path(new_stored_name)

    # Remove the old file from disk (best-effort)
    old_path = get_upload_path(doc.stored_name)
    try:
        if os.path.exists(old_path) and old_path != new_file_path:
            os.remove(old_path)
    except OSError:
        pass

    # Write new file
    async with aiofiles.open(new_file_path, "wb") as f:
        await f.write(content)

    # Drop old chunks and reset status
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))

    doc.stored_name   = new_stored_name
    doc.original_name = file.filename or doc.original_name
    doc.file_type     = new_file_type
    doc.file_size     = len(content)
    doc.status        = DocumentStatus.pending
    doc.chunk_count   = 0
    doc.error_message = None

    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(run_indexing_task, doc.id, new_file_path, new_file_type, user_id)

    folder_name: str | None = None
    if doc.folder_id:
        folder = await db.get(Folder, doc.folder_id)
        folder_name = folder.name if folder else None

    return _doc_to_response(doc, folder_name)
