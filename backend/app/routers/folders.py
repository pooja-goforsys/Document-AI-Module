import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.folder import FolderCreate, FolderRename, FolderResponse
from app.services import folder_service

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("/", response_model=list[FolderResponse])
async def list_folders(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await folder_service.list_folders(user_id, db)


@router.post("/", response_model=FolderResponse, status_code=201)
async def create_folder(
    body: FolderCreate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await folder_service.create_folder(body, user_id, db)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def rename_folder(
    folder_id: uuid.UUID,
    body: FolderRename,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await folder_service.rename_folder(folder_id, body, user_id, db)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await folder_service.delete_folder(folder_id, user_id, db)
