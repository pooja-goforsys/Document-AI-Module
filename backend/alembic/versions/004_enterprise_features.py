"""Enterprise features: pinned sessions, response modes, feedback, document summaries

Revision ID: 004
Revises: 003
Create Date: 2026-06-05 00:00:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Chat sessions: pinned flag
    op.add_column("chat_sessions", sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"))

    # Chat messages: response_mode
    op.add_column("chat_messages", sa.Column("response_mode", sa.String(20), nullable=True))

    # Documents: AI-generated summary
    op.add_column("documents", sa.Column("summary", sa.Text(), nullable=True))

    # Message feedback table
    op.create_table(
        "message_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id",  UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id",  ondelete="CASCADE"), nullable=False),
        sa.Column("user_id",    UUID(as_uuid=True), sa.ForeignKey("users.id",           ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),   # 'like' | 'dislike'
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"])
    op.create_index("ix_message_feedback_session_id", "message_feedback", ["session_id"])

    # FTS index on document_chunks content for hybrid search
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_fts ON document_chunks "
        "USING gin(to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunk_fts")
    op.drop_table("message_feedback")
    op.drop_column("documents", "summary")
    op.drop_column("chat_messages", "response_mode")
    op.drop_column("chat_sessions", "pinned")
