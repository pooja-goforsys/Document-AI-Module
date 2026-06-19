import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.signup(body, db)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.login(body, db)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout():
    # Token invalidation is handled client-side.
    # A token blacklist can be added here in the future.
    return {"message": "Logged out successfully"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.refresh_tokens(body.refresh_token, db)


@router.get("/me", response_model=UserResponse)
async def me(
    user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await auth_service.get_me(user_id, db)


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    raw_token = await auth_service.forgot_password(body.email, db)
    response: dict = {
        "message": "If an account with this email exists, a password reset link has been sent."
    }
    # Expose token only in development so the flow can be tested without email setup.
    # Remove or gate behind DEBUG flag before deploying to production.
    if raw_token:
        response["_dev_reset_token"] = raw_token
    return response


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    await auth_service.reset_password(body.token, body.new_password, db)
    return {"message": "Password updated successfully. You can now sign in."}
