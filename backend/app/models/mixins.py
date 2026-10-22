"""Shared ORM model mixins."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def str_uuid() -> Mapped[str]:
    """Column type helper for UUID primary keys stored as UUID, returned as str."""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    """Adds a server-side creation timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreatedUpdatedAtMixin(CreatedAtMixin):
    """Adds creation and update timestamps."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        onupdate=func.now(),
    )


__all__ = ["CreatedAtMixin", "CreatedUpdatedAtMixin", "str_uuid"]
