"""applications submitted_at timezone-aware

Revision ID: fe1b7d7b9254
Revises: 5ef6f1434d30
Create Date: 2026-10-23 13:14:31.392602

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "fe1b7d7b9254"
down_revision: str | None = "5ef6f1434d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make applications.submitted_at timezone-aware (safe: NULL-safe ALTER)."""
    op.alter_column(
        "applications",
        "submitted_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Revert to a naive timestamp (drops tz awareness, keeps values)."""
    op.alter_column(
        "applications",
        "submitted_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
    )
