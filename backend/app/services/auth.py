"""Authentication and session management.

Design (see docs/security.md):
- Passwords are Argon2id-hashed (`argon2-cffi`); plaintext is never stored or logged.
- Registration emails are validated with `email-validator` and uniqueness is
  enforced by the users.email constraint.
- Sessions are opaque, random 256-bit bearer tokens. Only the SHA-256 hash of
  the token is persisted in `user_sessions`; revocation means deleting the row.
- Login failures are counted per email by an in-process limiter; repeated
  failures lock that principal briefly.
- Credential errors are generic ("invalid email or password") for unknown
  accounts and wrong passwords alike.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User, UserProfile, UserSession

_hasher = PasswordHasher()  # Argon2id defaults

# Fixed-arg work item for logins against unknown accounts (or legacy rows with
# no password): every failed login performs one full Argon2 verify so response
# timing cannot distinguish "unknown email" from "wrong password".
_DUMMY_HASH = _hasher.hash("jobsoo-dummy-verify-" + secrets.token_hex(8))

SESSION_LIFETIME = timedelta(days=7)
_TOKEN_BYTES = 32

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class AuthError(Exception):
    """Authentication failure with an HTTP-friendly error code and status."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def hash_password(password: str) -> str:
    """Argon2id-hash a password (raises AuthError on policy violations)."""
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise AuthError(
            "weak_password",
            f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters",
        )
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time Argon2 verification; every failure is simply False."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
        return False


def normalize_email(email: str) -> str:
    """Fully lowercased, canonicalized email; raises on invalid addresses.

    The local part is lowercased too (RFC-discouraged but app-appropriate):
    two spellings differing only in case are treated as the same account.
    """
    try:
        checked = validate_email(email.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise AuthError("invalid_email", "invalid email address") from exc
    return checked.normalized.lower()


class LoginAttemptLimiter:
    """In-process sliding-window limiter for failed logins.

    Proportionate for a single-process local deployment: it stops brute force
    from one client without shared state. Multi-worker deployments would each
    hold their own table (documented limitation in docs/security.md).
    """

    def __init__(
        self, max_attempts: int = 10, window_seconds: float = 600.0, lockout_seconds: float = 300.0
    ) -> None:
        self.max_attempts = max_attempts
        self.window = timedelta(seconds=window_seconds)
        self.lockout = timedelta(seconds=lockout_seconds)
        self._attempts: dict[str, list[datetime]] = {}
        self._locked_until: dict[str, datetime] = {}

    def check(self, principal: str) -> None:
        """Raise AuthError("locked") while the principal is in lockout."""
        now = datetime.now(UTC)
        until = self._locked_until.get(principal)
        if until is not None and until > now:
            raise AuthError("locked", "too many failed attempts; try again later", 429)
        self._locked_until.pop(principal, None)

    def record_failure(self, principal: str) -> None:
        """Record one failed attempt; lock the principal past the threshold."""
        now = datetime.now(UTC)
        cutoff = now - self.window
        recent = [t for t in self._attempts.get(principal, []) if t > cutoff]
        recent.append(now)
        if len(recent) >= self.max_attempts:
            self._locked_until[principal] = now + self.lockout
            self._attempts.pop(principal, None)
        else:
            self._attempts[principal] = recent

    def reset(self, principal: str) -> None:
        """Clear history and lockout for a principal (also used by tests)."""
        self._attempts.pop(principal, None)
        self._locked_until.pop(principal, None)


limiter = LoginAttemptLimiter()


def register_user(
    session: Session, *, email: str, password: str, display_name: str = ""
) -> tuple[User, str]:
    """Create a user and their first session; returns `(user, raw_token)`.

    Commits here: a registration must not leave a half-created user without a
    way to authenticate. Raced duplicate registrations lose the unique-index
    toss-up and raise the same AuthError("duplicate_email", 409) as the
    upfront lookup (the loser rolls back, re-reads the winner, and 409s).
    """
    normalized = normalize_email(email)
    existing = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
    if existing is not None:
        raise AuthError("duplicate_email", "an account with this email already exists", 409)
    password_hash = hash_password(password)
    user = User(
        email=normalized,
        display_name=display_name or normalized.split("@")[0],
        password_hash=password_hash,
    )
    try:
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id))
        token = _create_session(session, user)
        session.commit()
    except IntegrityError:
        # A racing request committed this email first.
        session.rollback()
        winner = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
        if winner is None:  # not a duplicate-email race; surface the real error
            raise
        raise AuthError(
            "duplicate_email", "an account with this email already exists", 409
        ) from None
    return user, token


def authenticate(session: Session, *, email: str, password: str) -> tuple[User, str]:
    """Verify credentials; returns `(user, raw_token)` for the new session."""
    try:
        normalized = normalize_email(email)
    except AuthError as exc:
        raise AuthError("invalid_credentials", "invalid email or password", 401) from exc

    limiter.check(normalized)
    user = session.execute(select(User).where(User.email == normalized)).scalar_one_or_none()
    if user is None or user.password_hash is None:
        # Constant-work failure path: the dummy verify keeps the response time
        # of "unknown email" indistinguishable from "wrong password" and also
        # covers legacy rows whose password_hash is NULL.
        verify_password(_DUMMY_HASH, password)
        limiter.record_failure(normalized)
        raise AuthError("invalid_credentials", "invalid email or password", 401)
    if not verify_password(user.password_hash, password):
        limiter.record_failure(normalized)
        raise AuthError("invalid_credentials", "invalid email or password", 401)

    token = _create_session(session, user)
    limiter.reset(normalized)
    session.commit()
    return user, token


def _token_is_wellformed(token: str) -> bool:
    return len(token) == 2 * _TOKEN_BYTES and all(c in "0123456789abcdef" for c in token)


def _create_session(session: Session, user: User) -> str:
    """Mint one raw token and persist only its hash."""
    raw = secrets.token_hex(_TOKEN_BYTES)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + SESSION_LIFETIME,
        )
    )
    return raw


def resolve_session_token(session: Session, token: str) -> User | None:
    """Return the user owning a live token; None for unknown/expired tokens.

    Expired rows are deleted to keep the table small.
    """
    if not _token_is_wellformed(token):
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = session.execute(
        select(UserSession).where(UserSession.token_hash == digest)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at <= datetime.now(UTC):
        session.execute(delete(UserSession).where(UserSession.id == row.id))
        session.commit()
        return None
    return session.get(User, row.user_id)


def revoke_session_token(session: Session, token: str) -> None:
    """Delete the token row if it exists (idempotent logout)."""
    if not _token_is_wellformed(token):
        return
    digest = hashlib.sha256(token.encode()).hexdigest()
    session.execute(delete(UserSession).where(UserSession.token_hash == digest))
    session.commit()


__all__ = [
    "SESSION_LIFETIME",
    "AuthError",
    "LoginAttemptLimiter",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "authenticate",
    "hash_password",
    "limiter",
    "register_user",
    "resolve_session_token",
    "revoke_session_token",
    "verify_password",
]
