"""Add scope columns to chat_sessions for folder/document-specific chat

Revision ID: 002
Revises: 001
Create Date: 2026-06-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="all"),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("scope_name", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "scope_name")
    op.drop_column("chat_sessions", "scope_id")
    op.drop_column("chat_sessions", "scope_type")
