import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.user import User
from app.models.auth import PasswordResetToken
from app.schemas.auth import (
    SignupRequest, LoginRequest, TokenResponse, UserResponse,
    ResetPasswordRequest,
)
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.core.config import settings
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def _make_token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        user=_user_to_response(user),
    )


async def signup(request: SignupRequest, db: AsyncSession) -> TokenResponse:
    email = _normalize_email(str(request.email))
    existing = (await db.execute(
        select(User).where(func.lower(User.email) == email)
    )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=email,
        full_name=request.full_name.strip(),
        password_hash=hash_password(request.password),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"[Auth] New user registered: {user.email}")

    name = user.full_name or user.email.split("@")[0]
    await create_notification(
        user_id=user.id,
        title="Welcome to DocAI! 👋",
        message=f"Hi {name}! Your account is ready. Start by uploading a document.",
        notification_type="system",
        db=None,
    )

    return _make_token_response(user)


async def login(request: LoginRequest, db: AsyncSession) -> TokenResponse:
    email = _normalize_email(str(request.email))
    user = (await db.execute(
        select(User).where(func.lower(User.email) == email)
    )).scalar_one_or_none()

    if not user:
        logger.warning("[Auth] Login failed: no user for email=%s", email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.password_hash:
        logger.warning("[Auth] Login failed: user has no password hash email=%s", email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account does not have a password set. Please reset your password.",
        )

    if not verify_password(request.password, user.password_hash):
        logger.warning("[Auth] Login failed: password mismatch email=%s", email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated",
        )

    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    logger.info(f"[Auth] User logged in: {user.email}")

    name = user.full_name or user.email.split("@")[0]
    await create_notification(
        user_id=user.id,
        title="Signed in successfully",
        message=f"Welcome back, {name}! You signed in to DocAI.",
        notification_type="system",
        db=None,
    )

    return _make_token_response(user)


async def get_me(user_id: uuid.UUID, db: AsyncSession) -> UserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_to_response(user)


async def refresh_tokens(refresh_token: str, db: AsyncSession) -> TokenResponse:
    try:
        payload = decode_token(refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return _make_token_response(user)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def forgot_password(email: str, db: AsyncSession) -> str:
    """Return the raw reset token (logged; in production this would be emailed)."""
    normalized_email = _normalize_email(str(email))
    user = (await db.execute(
        select(User).where(func.lower(User.email) == normalized_email)
    )).scalar_one_or_none()

    if not user:
        return ""  # Don't reveal whether email exists

    # Mark any existing unused tokens as used
    old = (await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False,  # noqa: E712
        )
    )).scalars().all()
    for tok in old:
        tok.used = True

    raw_token = str(uuid.uuid4())
    prt = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(prt)
    await db.commit()

    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
    logger.info(f"[Auth] Password reset link for {normalized_email}: {reset_link}")
    # TODO: send_reset_email(email, user.full_name, reset_link)

    return raw_token


async def reset_password(token: str, new_password: str, db: AsyncSession) -> None:
    token_hash = _hash_token(token)
    prt = (await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,  # noqa: E712
        )
    )).scalar_one_or_none()

    if not prt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already-used reset token",
        )

    now = datetime.now(timezone.utc)
    expires = prt.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired — please request a new one",
        )

    user = await db.get(User, prt.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(new_password)
    prt.used = True
    await db.commit()
    logger.info(f"[Auth] Password reset completed for user {user.email}")
