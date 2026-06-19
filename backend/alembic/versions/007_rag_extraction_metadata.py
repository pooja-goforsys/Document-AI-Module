"""Add RAG extraction and embedding metadata.

Revision ID: 007_rag_extraction_metadata
Revises: 006_chunk_category_metadata
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_rag_extraction_metadata"
down_revision = "006_chunk_category_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("source_document", sa.String(500), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(200), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_version", sa.String(100), nullable=True))
    op.add_column("document_chunks", sa.Column("extraction_metadata", postgresql.JSONB(), nullable=True))
    op.create_index("ix_document_chunks_embedding_version", "document_chunks", ["embedding_version"])


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_version", table_name="document_chunks")
    op.drop_column("document_chunks", "extraction_metadata")
    op.drop_column("document_chunks", "embedding_version")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "source_document")
