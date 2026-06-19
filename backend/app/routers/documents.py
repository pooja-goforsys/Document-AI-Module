import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_from_token_or_param
from app.core.exceptions import NotFoundError
from app.schemas.document import DocumentResponse, UploadResponse, DocumentUpdate, SummarizeRequest, SummarizeResponse
from app.services import document_service
from app.services import summarize_service
from app.utils.file_utils import get_upload_path

router = APIRouter(prefix="/documents", tags=["documents"])

_MIME = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt":  "text/plain; charset=utf-8",
}


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await document_service.upload_and_index(file, folder_id, user_id, db, background_tasks)


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    folder_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await document_service.list_documents(user_id, folder_id, db, page, page_size)


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await document_service.get_document(doc_id, user_id, db)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: uuid.UUID,
    body: DocumentUpdate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a document and / or move it to a different folder.
    Send `folder_id: null` to move it out of any folder."""
    return await document_service.update_document(doc_id, body, user_id, db)


@router.put("/{doc_id}/file", response_model=DocumentResponse)
async def replace_file(
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the stored file with a new upload and re-trigger indexing."""
    return await document_service.replace_file(doc_id, file, user_id, db, background_tasks)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await document_service.delete_document(doc_id, user_id, db)


@router.get("/{doc_id}/file")
async def serve_file(
    doc_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_from_token_or_param),
    db: AsyncSession = Depends(get_db),
):
    """Stream the original file. PDFs open inline in the browser; others trigger download."""
    from app.models.document import Document as DocModel
    doc = await db.get(DocModel, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")

    file_path = get_upload_path(doc.stored_name)
    if not os.path.exists(file_path):
        raise NotFoundError("File not found on disk")

    media_type  = _MIME.get(doc.file_type, "application/octet-stream")
    safe_name   = doc.original_name.replace('"', "'")
    disposition = "inline" if doc.file_type == "pdf" else "attachment"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=doc.original_name,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_name}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post("/{doc_id}/reindex")
async def reindex_document(
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await document_service.reindex_document(doc_id, user_id, db, background_tasks)


@router.post("/{doc_id}/summarize", response_model=SummarizeResponse)
async def summarize_document(
    doc_id: uuid.UUID,
    body: SummarizeRequest,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an AI summary of a document. scope: full | executive | key_takeaways"""
    return await summarize_service.summarize_document(doc_id, user_id, body.scope, db)
