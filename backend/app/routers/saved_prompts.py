import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.schemas.saved_prompt import SavedPromptCreate, SavedPromptUpdate, SavedPromptResponse
from app.services import saved_prompt_service as svc

router = APIRouter(prefix="/saved-prompts", tags=["Saved Prompts"])


@router.get("/", response_model=list[SavedPromptResponse])
async def list_saved_prompts(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    return await svc.list_prompts(user_id, db)


@router.post("/", response_model=SavedPromptResponse, status_code=201)
async def create_saved_prompt(
    body: SavedPromptCreate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    return await svc.create_prompt(user_id, body, db)


@router.patch("/{prompt_id}", response_model=SavedPromptResponse)
async def update_saved_prompt(
    prompt_id: uuid.UUID,
    body: SavedPromptUpdate,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    return await svc.update_prompt(prompt_id, user_id, body, db)


@router.post("/{prompt_id}/use", status_code=204)
async def record_prompt_use(
    prompt_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    await svc.increment_use_count(prompt_id, user_id, db)


@router.delete("/{prompt_id}", status_code=204)
async def delete_saved_prompt(
    prompt_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
):
    await svc.delete_prompt(prompt_id, user_id, db)
