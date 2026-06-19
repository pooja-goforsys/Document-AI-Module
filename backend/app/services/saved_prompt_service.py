import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.saved_prompt import SavedPrompt
from app.schemas.saved_prompt import SavedPromptCreate, SavedPromptUpdate
from app.core.exceptions import NotFoundError


async def list_prompts(user_id: uuid.UUID, db: AsyncSession) -> list[SavedPrompt]:
    stmt = (
        select(SavedPrompt)
        .where(SavedPrompt.user_id == user_id)
        .order_by(SavedPrompt.is_pinned.desc(), SavedPrompt.use_count.desc(), SavedPrompt.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_prompt(
    user_id: uuid.UUID,
    data: SavedPromptCreate,
    db: AsyncSession,
) -> SavedPrompt:
    prompt = SavedPrompt(
        user_id=user_id,
        title=data.title.strip(),
        content=data.content.strip(),
        response_mode=data.response_mode,
        category=data.category,
    )
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return prompt


async def update_prompt(
    prompt_id: uuid.UUID,
    user_id: uuid.UUID,
    data: SavedPromptUpdate,
    db: AsyncSession,
) -> SavedPrompt:
    prompt = await db.get(SavedPrompt, prompt_id)
    if not prompt or prompt.user_id != user_id:
        raise NotFoundError("Saved prompt")

    if data.title     is not None: prompt.title         = data.title.strip()
    if data.content   is not None: prompt.content       = data.content.strip()
    if data.response_mode is not None: prompt.response_mode = data.response_mode
    if data.category  is not None: prompt.category      = data.category
    if data.is_pinned is not None: prompt.is_pinned     = data.is_pinned

    await db.commit()
    await db.refresh(prompt)
    return prompt


async def increment_use_count(
    prompt_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    prompt = await db.get(SavedPrompt, prompt_id)
    if prompt and prompt.user_id == user_id:
        prompt.use_count += 1
        await db.commit()


async def delete_prompt(
    prompt_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    prompt = await db.get(SavedPrompt, prompt_id)
    if not prompt or prompt.user_id != user_id:
        raise NotFoundError("Saved prompt")
    await db.delete(prompt)
    await db.commit()
