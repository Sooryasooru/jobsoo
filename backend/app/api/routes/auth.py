"""Authentication routes: register, login, logout, current user.

Public endpoints: /auth/register, /auth/login, /auth/logout, /health.
Every other router depends on `get_current_user` (see app/main.py).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.deps import CurrentAuthenticatedUser
from app.db.session import get_session
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, SessionTokenResponse, UserResponse
from app.services import auth
from app.services.auth import AuthError

_bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_token_payload(user: User, token: str) -> SessionTokenResponse:
    return SessionTokenResponse(token=token, user=UserResponse.model_validate(user))


@router.post("/register", response_model=SessionTokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest, session: Annotated[Session, Depends(get_session)]
) -> SessionTokenResponse:
    """Create an account and one live session."""
    try:
        user, token = auth.register_user(
            session,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return _session_token_payload(user, token)


@router.post("/login", response_model=SessionTokenResponse)
def login(
    payload: LoginRequest, session: Annotated[Session, Depends(get_session)]
) -> SessionTokenResponse:
    """Exchange credentials for a fresh bearer session."""
    try:
        user, token = auth.authenticate(session, email=payload.email, password=payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    return _session_token_payload(user, token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> None:
    """Revoke the presented session token (idempotent, token optional)."""
    token = credentials.credentials if credentials is not None else ""
    auth.revoke_session_token(session, token)
    request.state.logout = True  # observable for tests; never contains credentials


@router.get("/me", response_model=UserResponse)
def me(user: CurrentAuthenticatedUser) -> User:
    """Return the authenticated identity."""
    return user


__all__ = ["router"]
