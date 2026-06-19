"""Notification system: notifications table

Revision ID: 005
Revises: 004
Create Date: 2026-06-05 00:00:00.000000

Adds:
  - notifications table with compound index on (user_id, is_read)
  - created_at index for sort performance
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title",   sa.String(255), nullable=False),
        sa.Column("message", sa.Text(),      nullable=False),
        sa.Column("type",    sa.String(20),  nullable=False, server_default="system"),
        sa.Column("is_read", sa.Boolean(),   nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # Compound index: fast "unread notifications for user X" queries
    op.create_index("ix_notifications_user_unread", "notifications", ["user_id", "is_read"])
    # Sort index: ORDER BY created_at DESC
    op.create_index("ix_notifications_created_at",  "notifications", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at",  "notifications")
    op.drop_index("ix_notifications_user_unread", "notifications")
    op.drop_table("notifications")
