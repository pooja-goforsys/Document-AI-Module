import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.folder import Folder
from app.models.document import Document
from app.schemas.folder import FolderCreate, FolderRename, FolderResponse
from app.core.exceptions import NotFoundError


async def list_folders(user_id: uuid.UUID, db: AsyncSession) -> list[FolderResponse]:
    stmt = (
        select(Folder, func.count(Document.id).label("doc_count"))
        .outerjoin(Document, Document.folder_id == Folder.id)
        .where(Folder.user_id == user_id)
        .group_by(Folder.id)
        .order_by(Folder.created_at.asc())
    )
    rows = await db.execute(stmt)
    result = []
    for folder, count in rows.all():
        result.append(FolderResponse(
            id=folder.id,
            name=folder.name,
            document_count=count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        ))
    return result


async def create_folder(body: FolderCreate, user_id: uuid.UUID, db: AsyncSession) -> FolderResponse:
    folder = Folder(name=body.name, user_id=user_id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderResponse(id=folder.id, name=folder.name, document_count=0,
                          created_at=folder.created_at, updated_at=folder.updated_at)


async def rename_folder(folder_id: uuid.UUID, body: FolderRename, user_id: uuid.UUID, db: AsyncSession) -> FolderResponse:
    folder = await db.get(Folder, folder_id)
    if not folder or folder.user_id != user_id:
        raise NotFoundError("Folder")
    folder.name = body.name
    await db.commit()
    await db.refresh(folder)
    return FolderResponse(id=folder.id, name=folder.name, document_count=0,
                          created_at=folder.created_at, updated_at=folder.updated_at)


async def delete_folder(folder_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    folder = await db.get(Folder, folder_id)
    if not folder or folder.user_id != user_id:
        raise NotFoundError("Folder")
    await db.delete(folder)
    await db.commit()
