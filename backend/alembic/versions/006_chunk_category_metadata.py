"""Add chunk category metadata for retrieval filtering

Revision ID: 006
Revises: 005
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("category", sa.String(100), nullable=True))
    op.create_index("ix_document_chunks_category", "document_chunks", ["category"])


def downgrade() -> None:
    op.drop_index("ix_document_chunks_category", table_name="document_chunks")
    op.drop_column("document_chunks", "category")
