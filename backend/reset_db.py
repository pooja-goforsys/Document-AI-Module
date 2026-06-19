"""
One-time database reset script.
Drops all old tables (integer-ID schema) and lets the app recreate them
with the correct UUID schema on next startup.

Usage:
    cd backend
    venv\Scripts\python reset_db.py
"""
import os
import sys
import psycopg2
from urllib.parse import urlparse, unquote

# ── Read DATABASE_URL from .env ───────────────────────────────────────────────
env_path = os.path.join(os.path.dirname(__file__), ".env")
db_url = None
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            db_url = line.split("=", 1)[1].strip()
            break

if not db_url:
    print("ERROR: DATABASE_URL not found in .env")
    sys.exit(1)

# asyncpg uses postgresql+asyncpg:// — strip driver prefix for psycopg2
db_url_sync = db_url.replace("postgresql+asyncpg://", "postgresql://")

print(f"Connecting to: {db_url_sync[:40]}...")

try:
    conn = psycopg2.connect(db_url_sync)
    conn.autocommit = True
    cur = conn.cursor()

    # Check what tables exist
    cur.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename;
    """)
    existing = [row[0] for row in cur.fetchall()]
    print(f"Found tables: {existing}")

    if not existing:
        print("Database is already empty. Nothing to reset.")
    else:
        # Check if old integer-ID schema is present
        cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'id'
            AND table_schema = 'public';
        """)
        row = cur.fetchone()
        if row and row[0] == 'integer':
            print("Detected old INTEGER-based schema. Dropping all old tables...")
        else:
            print("Dropping all tables for clean recreation...")

        # Drop everything
        drop_sql = """
            DROP TABLE IF EXISTS
                chat_messages, chat_sessions,
                document_chunks, documents,
                folders, users,
                messages, chunks, conversations,
                refresh_tokens
            CASCADE;
        """
        cur.execute(drop_sql)
        print("All old tables dropped.")

    cur.close()
    conn.close()
    print()
    print("Reset complete!")
    print("Now start the backend — it will create fresh tables automatically:")
    print()
    print("    cd backend")
    print("    venv\\Scripts\\uvicorn app.main:app --reload")

except psycopg2.OperationalError as e:
    print(f"ERROR: Could not connect to database: {e}")
    print("Make sure PostgreSQL is running and DATABASE_URL in .env is correct.")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
