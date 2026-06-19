"""
FastAPI dependencies — JWT-based authentication.

Every protected endpoint injects get_current_user which extracts the
user_id from a Bearer access token. The token is validated against the
SECRET_KEY, and the user must exist and be active in the database.

For the document file-serve endpoint (browser <img> / direct URL access),
the token may also be passed as a ?token= query parameter.
"""
import uuid

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_user_id(token: str) -> uuid.UUID:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise _UNAUTH
        return uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise _UNAUTH


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Standard dependency: Bearer token in Authorization header."""
    if not credentials:
        raise _UNAUTH

    user_id = _extract_user_id(credentials.credentials)
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise _UNAUTH

    return user.id


async def get_current_user_from_token_or_param(
    token_param: str | None = Query(None, alias="token"),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Extended dependency: accepts token from Bearer header OR ?token= query param.
    Used for file-serve endpoints where the browser fetches the URL directly."""
    raw_token = credentials.credentials if credentials else token_param
    if not raw_token:
        raise _UNAUTH

    user_id = _extract_user_id(raw_token)
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise _UNAUTH

    return user.id
