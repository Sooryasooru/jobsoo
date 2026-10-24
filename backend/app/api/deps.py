"""FastAPI dependencies: authenticated request identity.

The acting user is derived exclusively from the `Authorization: Bearer`
session token. No route may trust a client-supplied user id.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import User
from app.services import auth

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    """Resolve the acting user from the bearer token, or 401."""
    token = credentials.credentials if credentials is not None else ""
    user = auth.resolve_session_token(session, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentAuthenticatedUser = Annotated[User, Depends(get_current_user)]
