"""User helpers for the Phase 1 single-user prototype.

Authentication is deliberately deferred (docs/security.md). All Phase 1
routes operate on an auto-created development user taken from settings.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, UserProfile


def get_or_create_dev_user(session: Session) -> User:
    """Return the prototype user, creating it and its profile on first use."""
    email = get_settings().dev_user_email
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, display_name="Dev Candidate")
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id))
        session.commit()
    return user
