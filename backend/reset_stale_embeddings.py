"""
One-shot fix for the embedding dimension mismatch that breaks every chat query.

Problem:
  Your DB has 1581 chunks stored at 768 dimensions (from an older embedding
  model). The current embedder is sentence-transformers/all-MiniLM-L6-v2
  which produces 384-dim vectors. Every query embedding is dimension-checked
  against stored embeddings and silently dropped, so retrieval returns nothing
  useful and the chat fails downstream.

What this script does:
  1) Counts the stale 768-dim chunks (read-only — shows what it WILL delete).
  2) Asks for explicit y/N confirmation.
  3) Deletes the 768-dim chunks.
  4) Sets the affected documents back to status='pending' so the next uvicorn
     startup auto-recovers them and re-indexes with the current 384-dim model.

How to run (from backend/ directory, with venv activated):
  python reset_stale_embeddings.py

Then restart uvicorn:
  python -m uvicorn app.main:app --reload

Recovery runs automatically at startup. Chat works once indexing finishes
(usually a few minutes for a textbook-sized PDF).
"""
import asyncio
import sys

import app.models.notification   # noqa — register models so SA mappers compile
import app.models.auth           # noqa
import app.models.saved_prompt   # noqa
import app.models.analytics      # noqa

from app.core.database import engine
from sqlalchemy import text


async def show_state() -> tuple[int, int]:
    """Return (stale_chunks_768, docs_to_reset)."""
    async with engine.connect() as c:
        stale = (await c.execute(text("""
            SELECT COUNT(*) FROM document_chunks
            WHERE array_length(embedding, 1) = 768
        """))).scalar() or 0

        affected_docs = (await c.execute(text("""
            SELECT d.id, d.original_name,
                   COUNT(c.id) FILTER (WHERE array_length(c.embedding,1) = 768) AS chunks_768,
                   COUNT(c.id) FILTER (WHERE array_length(c.embedding,1) = 384) AS chunks_384
            FROM documents d
            LEFT JOIN document_chunks c ON c.document_id = d.id
            GROUP BY d.id
            HAVING COUNT(c.id) FILTER (WHERE array_length(c.embedding,1) = 768) > 0
            ORDER BY chunks_768 DESC
        """))).all()

    print(f"\nStale 768-dim chunks: {stale}")
    print(f"Affected documents  : {len(affected_docs)}")
    for row in affected_docs:
        print(f"  {row[1]!r:50s}  chunks_768={row[2]}  chunks_384={row[3]}")
    return stale, len(affected_docs)


async def apply_fix() -> None:
    async with engine.begin() as c:
        del_res = await c.execute(text("""
            DELETE FROM document_chunks
            WHERE array_length(embedding, 1) = 768
        """))
        print(f"[OK] Deleted {del_res.rowcount} stale 768-dim chunks")

        # Reset only documents that have NO valid 384-dim chunks left
        # (don't disturb docs that already have current-model chunks).
        upd_res = await c.execute(text("""
            UPDATE documents
            SET status = 'pending', error_message = NULL, chunk_count = 0
            WHERE id IN (
                SELECT id FROM documents d
                WHERE NOT EXISTS (
                    SELECT 1 FROM document_chunks c
                    WHERE c.document_id = d.id
                      AND array_length(c.embedding,1) = 384
                )
            )
        """))
        print(f"[OK] Set {upd_res.rowcount} document(s) back to 'pending'")

    print("\nDone. Restart uvicorn — the lifespan recovery will re-index "
          "every pending document with the current 384-dim model.")


async def main() -> None:
    stale, n_docs = await show_state()
    if stale == 0:
        print("\nNo stale chunks — nothing to do.")
        return

    print(
        "\nThis will DELETE the stale chunks above and reset their documents "
        "to 'pending' so they get re-indexed at next startup."
    )
    answer = input("Proceed? [y/N]: ").strip().lower()
    if answer != "y":
        print("Aborted. No changes made.")
        return

    await apply_fix()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
