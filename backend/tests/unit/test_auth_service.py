"""Unit tests for password hashing, validation, and the login limiter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.auth import (
    AuthError,
    LoginAttemptLimiter,
    hash_password,
    normalize_email,
    verify_password,
)


def test_hash_password_and_verify_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2")
    assert hashed != "correct horse battery staple"
    assert verify_password(hashed, "correct horse battery staple") is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("s3cret-pass")
    assert verify_password(hashed, "wrong-pass") is False


def test_verify_password_rejects_corrupt_hash() -> None:
    assert verify_password("not-a-hash", "anything") is False


def test_hash_password_enforces_minimum_length() -> None:
    with pytest.raises(AuthError, match="password must be"):
        hash_password("short")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("User@Example.COM", "user@example.com"),
        ("user+tag@example.com", "user+tag@example.com"),
        ("  spaced@example.com  ", "spaced@example.com"),
    ],
)
def test_normalize_email_canonicalizes(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["not-an-email", "missing-at@", "bad@"])
def test_normalize_email_rejects_invalid(raw: str) -> None:
    with pytest.raises(AuthError, match="invalid email"):
        normalize_email(raw)


def test_limiter_locks_after_threshold() -> None:
    limiter = LoginAttemptLimiter(max_attempts=3, window_seconds=60, lockout_seconds=120)
    for _ in range(3):
        limiter.record_failure("user@x.com")
    with pytest.raises(AuthError, match="too many failed attempts"):
        limiter.check("user@x.com")


def test_limiter_unlocks_after_lockout() -> None:
    limiter = LoginAttemptLimiter(max_attempts=2, window_seconds=60, lockout_seconds=120)
    limiter.record_failure("user@x.com")
    limiter.record_failure("user@x.com")
    limiter._locked_until["user@x.com"] = datetime.now(UTC) - timedelta(seconds=1)
    limiter.check("user@x.com")  # expired lockout is cleared, no raise


def test_limiter_failures_expire_after_window() -> None:
    limiter = LoginAttemptLimiter(max_attempts=2, window_seconds=60, lockout_seconds=120)
    stale = datetime.now(UTC) - timedelta(seconds=120)
    limiter._attempts["user@x.com"] = [stale, stale]
    # Both stale entries are scoured; only the fresh failure counts.
    limiter.record_failure("user@x.com")
    limiter.check("user@x.com")  # not locked


def test_limiter_isolated_per_principal() -> None:
    limiter = LoginAttemptLimiter(max_attempts=2, window_seconds=60, lockout_seconds=120)
    limiter.record_failure("a@x.com")
    limiter.record_failure("a@x.com")
    limiter.check("b@x.com")  # other principal unaffected
