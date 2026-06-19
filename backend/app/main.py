import logging
import logging.config
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

# ── Logging setup ─────────────────────────────────────────────────────────────
# Configure before anything else so all module-level loggers inherit this.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
# Quieten noisy third-party loggers
for _noisy in ("sqlalchemy.engine", "httpcore", "httpx", "sentence_transformers",
               "transformers", "torch"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.database import engine, Base
from app.core.exceptions import AppError, app_error_handler
from app.routers import folders, documents, chat, stats, notifications, auth
from app.routers import saved_prompts, analytics as analytics_router
from app.routers import debug as debug_router
import app.models.notification   # noqa — ensure Alembic/metadata tracks this model
import app.models.auth            # noqa — ensure password_reset_tokens table is created
import app.models.saved_prompt    # noqa
import app.models.analytics       # noqa

# ── Startup state (read by /health) ──────────────────────────────────────────
_startup = {
    "database":         "disconnected",
    "tables":           "not_created",
    "pgvector":         "disabled",
    "embedder":         "not_loaded",
    "ai_provider":      "not_loaded",
    "gemini_status":    "not_checked",
    "vector_search":    "disabled",
}


async def _check_schema_conflict(conn: AsyncConnection) -> bool:
    """Return True if old integer-ID tables are present."""
    result = await conn.execute(text("""
        SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'users'
          AND column_name  = 'id'
    """))
    row = result.fetchone()
    return row is not None and row[0] == "integer"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "=" * 55)
    print("  Chat-with-Your-Documents — Backend Starting")
    print("=" * 55)

    # ── 1. Database connectivity ──────────────────────────────────
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        _startup["database"] = "connected"
        print("[DB]        connected")
    except Exception as exc:
        _startup["database"] = f"error: {exc}"
        print(f"[DB]        FAILED — {exc}")
        print("            Fix DATABASE_URL in backend/.env and restart.")
        yield
        return

    # ── 2. Schema conflict check ──────────────────────────────────
    try:
        async with engine.begin() as conn:
            conflict = await _check_schema_conflict(conn)
        if conflict:
            print("[DB]        WARNING — old INTEGER-ID schema detected!")
            print("            Run:  python reset_db.py  then restart.")
            _startup["tables"] = "schema_conflict"
            yield
            return
    except Exception:
        pass  # table may not exist yet — that's fine

    # ── 3. Table creation ─────────────────────────────────────────
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _startup["tables"] = "ready"
        print("[Tables]    created / verified")
    except Exception as exc:
        _startup["tables"] = f"error: {exc}"
        print(f"[Tables]    FAILED — {exc}")
        if "incompatible types" in str(exc) or "uuid" in str(exc).lower():
            print("            Schema conflict detected. Run:  python reset_db.py")
        yield
        return

    # ── 3b. Schema migration — add columns that may be missing from existing tables ──
    _migration_sql = [
        # chat_sessions: enterprise columns added after initial schema
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS scope_type VARCHAR(20) NOT NULL DEFAULT 'all'",
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS scope_id UUID",
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS scope_name VARCHAR(500)",
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE",
        # chat_messages: enterprise columns added after initial schema
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS confidence_score FLOAT",
        "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS response_mode VARCHAR(20)",
        # documents: summary + domain columns (may already exist)
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary TEXT",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS domain_name VARCHAR(200)",
        # users: auth columns (may already exist)
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE",
        # saved_prompts table (created via create_all above, migration guards for existing DBs)
        """
        CREATE TABLE IF NOT EXISTS saved_prompts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(200) NOT NULL,
            content TEXT NOT NULL,
            response_mode VARCHAR(20),
            category VARCHAR(100),
            use_count INTEGER NOT NULL DEFAULT 0,
            is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_saved_prompts_user_id ON saved_prompts(user_id)",
        # query_analytics table
        """
        CREATE TABLE IF NOT EXISTS query_analytics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            session_id UUID,
            original_query TEXT NOT NULL,
            expanded_query TEXT,
            response_mode VARCHAR(20),
            scope_type VARCHAR(20),
            chunks_retrieved INTEGER,
            docs_searched INTEGER,
            confidence_score FLOAT,
            response_time_ms INTEGER,
            entities_extracted JSONB,
            top_chunks JSONB,
            used_pgvector VARCHAR(10),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_query_analytics_user_id ON query_analytics(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_query_analytics_created_at ON query_analytics(created_at DESC)",
        # document_chunks: section heading for metadata-based retrieval filtering
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS section_heading VARCHAR(500)",
        # document_chunks: category for retrieval noise filtering (migration 006)
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS category VARCHAR(100)",
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_category ON document_chunks (category)",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS source_document VARCHAR(500)",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(200)",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_version VARCHAR(100)",
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS extraction_metadata JSONB",
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_version ON document_chunks (embedding_version)",
    ]
    try:
        async with engine.begin() as conn:
            for _sql in _migration_sql:
                await conn.execute(text(_sql))
        print("[Migrate]   schema columns verified / added")
    except Exception as exc:
        print(f"[Migrate]   WARNING — schema migration failed: {exc}")
        print("            Chat features may not work. Check logs for details.")

    # ── 3c. Embedding-dimension mismatch repair ────────────────────────
    # Chunks whose stored embedding dimension differs from the currently
    # configured EMBEDDING_DIMENSION are unreachable by retrieval (the
    # dimension guard in retrieval drops them). Wipe them and reset the
    # affected documents to 'pending' so the recovery in step 7 below
    # re-indexes them with the current embedder. Safe + idempotent —
    # only runs when a mismatch is actually present.
    try:
        async with engine.begin() as conn:
            _target_dim = settings.EMBEDDING_DIMENSION
            _r = await conn.execute(text(
                "SELECT COUNT(*) FROM document_chunks "
                "WHERE embedding IS NOT NULL "
                "AND COALESCE(array_length(embedding, 1), 0) <> :d"
            ), {"d": _target_dim})
            _mismatched = _r.scalar() or 0
            if _mismatched > 0:
                print(
                    f"[DimRepair] Found {_mismatched} chunk(s) with wrong embedding "
                    f"dim (target={_target_dim}) — wiping so they can be re-indexed"
                )
                await conn.execute(text(
                    "DELETE FROM document_chunks "
                    "WHERE embedding IS NOT NULL "
                    "AND COALESCE(array_length(embedding, 1), 0) <> :d"
                ), {"d": _target_dim})
                _u = await conn.execute(text(
                    "UPDATE documents SET status='pending', "
                    "error_message=NULL, chunk_count=0 "
                    "WHERE id IN ("
                    "  SELECT d.id FROM documents d "
                    "  WHERE NOT EXISTS ("
                    "    SELECT 1 FROM document_chunks c "
                    "    WHERE c.document_id = d.id "
                    "      AND COALESCE(array_length(c.embedding, 1), 0) = :d"
                    "  )"
                    ")"
                ), {"d": _target_dim})
                print(
                    f"[DimRepair] {_u.rowcount} document(s) reset to 'pending'; "
                    "recovery step will re-index them"
                )
            else:
                print(f"[DimRepair] All embeddings match target dim {_target_dim} — OK")
    except Exception as _dr_exc:
        print(f"[DimRepair] WARNING — could not check/repair embedding dims: {_dr_exc}")

    # ── 4. pgvector extension ─────────────────────────────────────
    from app.core import pgvector_search as _pv
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # Verify the <=> operator works (proves extension is functional)
            await conn.execute(text("SELECT '[0.1,0.2,0.3]'::vector(3) <=> '[0.1,0.2,0.4]'::vector(3)"))
        _startup["pgvector"] = "enabled"
        _startup["vector_search"] = "pgvector_native"
        _pv.set_available(True)
        print("[pgvector]  enabled — native SQL vector search active")
    except Exception as _pv_exc:
        _startup["pgvector"] = "disabled"
        _startup["vector_search"] = "python_cosine"
        _pv.set_available(False)
        print(f"[pgvector]  not installed — Python cosine fallback ({_pv_exc})")

    # ── 5. Embedder warm-up ───────────────────────────────────────
    # Call embed_query() now so the model is fully loaded before the first
    # document upload arrives.  Without this the first upload has to wait for
    # the model download (up to several minutes) before embedding can begin,
    # leaving the document stuck in 'indexing' for a long time.
    try:
        from app.embedders import get_embedder
        _embedder = get_embedder()
        await _embedder.embed_query("startup warmup")
        _startup["embedder"] = "loaded"
        print(f"[Embedder]  loaded ({settings.EMBEDDING_PROVIDER})")
    except Exception as exc:
        _startup["embedder"] = f"error: {exc}"
        print(f"[Embedder]  failed — {exc}")
        print(f"            Uploads will work but indexing may be slow on first document.")

    # ── 6. AI provider chain warm-up ─────────────────────────────
    def _mask_key(k: str) -> str:
        k = (k or "").strip()
        if not k:
            return "<missing>"
        return (k[:6] + "…" + k[-4:]) if len(k) > 12 else "<short>"

    print(f"[AI]        keys detected — "
          f"GEMINI={_mask_key(settings.GEMINI_API_KEY)}  "
          f"OPENAI={_mask_key(settings.OPENAI_API_KEY)}  "
          f"ANTHROPIC={_mask_key(settings.ANTHROPIC_API_KEY)}")
    try:
        from app.ai_providers import get_ordered_provider_chain, _is_provider_configured
        chain = get_ordered_provider_chain()
        if chain:
            chain_names = [n for n, _ in chain]
            _startup["ai_provider"]   = f"ready — chain: {chain_names}"
            _startup["gemini_status"] = "configured"
            print(f"[AI]        active provider: {chain_names[0]}  fallback chain: {chain_names[1:] or '[]'}")
        else:
            _startup["ai_provider"]   = "disabled — no providers configured"
            _startup["gemini_status"] = "missing_api_key"
            print("[AI]        ══════════════════════════════════════════════")
            print("[AI]        NO AI PROVIDERS CONFIGURED — chat is disabled")
            print("[AI]        Every query will return 'generation unavailable'")
            print("[AI]        ──────────────────────────────────────────────")
            print("[AI]        Fix: add at least one key to backend/.env")
            print("[AI]          GEMINI_API_KEY=AIzaSy...   (get free key at aistudio.google.com)")
            print("[AI]          OPENAI_API_KEY=sk-...")
            print("[AI]          ANTHROPIC_API_KEY=sk-ant-...")
            print("[AI]        Then restart the server.")
            print("[AI]        ══════════════════════════════════════════════")
    except Exception as exc:
        _startup["ai_provider"]   = f"error: {exc}"
        _startup["gemini_status"] = "error"
        print(f"[AI]        provider chain check failed — {exc}")

    # ── 7. Recovery — re-queue documents stuck in pending/indexing ────────────
    # FastAPI BackgroundTasks live only in RAM; a server restart leaves any
    # in-progress or queued documents frozen forever.  Detect them and
    # re-launch their indexing tasks as async coroutines so they complete.
    import asyncio as _asyncio
    from app.core.database import AsyncSessionLocal as _ASL
    from app.models.document import Document as _Doc, DocumentStatus as _DS
    from app.tasks.indexing_task import run_indexing_task as _reindex
    from app.utils.file_utils import get_upload_path as _gup
    from sqlalchemy import select as _sel, update as _upd

    try:
        async with _ASL() as _rdb:
            _stuck = (await _rdb.execute(
                _sel(_Doc).where(_Doc.status.in_([_DS.pending, _DS.indexing]))
            )).scalars().all()

        if _stuck:
            print(f"[Recovery]  {len(_stuck)} document(s) stuck — re-queuing now")
            # Reset each to pending so the task starts cleanly
            async with _ASL() as _rdb2:
                await _rdb2.execute(
                    _upd(_Doc)
                    .where(_Doc.status.in_([_DS.pending, _DS.indexing]))
                    .values(status=_DS.pending, error_message=None)
                )
                await _rdb2.commit()
            for _d in _stuck:
                _fp = _gup(_d.stored_name)
                _asyncio.create_task(
                    _reindex(_d.id, _fp, _d.file_type, _d.user_id)
                )
                print(f"[Recovery]  re-queued: {_d.original_name!r} ({_d.id})")
        else:
            print("[Recovery]  no stuck documents found")
    except Exception as _rec_exc:
        print(f"[Recovery]  WARNING — recovery scan failed: {_rec_exc}")

    print("=" * 55)
    print("  Startup complete — http://127.0.0.1:8000")
    print("  Health check   — http://127.0.0.1:8000/health")
    print("=" * 55 + "\n")

    yield

    await engine.dispose()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Document AI API",
    version="1.0.0",
    description="Production-grade RAG system for document Q&A",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Error handlers ────────────────────────────────────────────────────────────
app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Internal server error"},
    )


# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth.router,              prefix=API_PREFIX)
app.include_router(folders.router,           prefix=API_PREFIX)
app.include_router(documents.router,         prefix=API_PREFIX)
app.include_router(chat.router,              prefix=API_PREFIX)
app.include_router(stats.router,             prefix=API_PREFIX)
app.include_router(notifications.router,     prefix=API_PREFIX)
app.include_router(saved_prompts.router,     prefix=API_PREFIX)
app.include_router(analytics_router.router,  prefix=API_PREFIX)
app.include_router(debug_router.router,      prefix=API_PREFIX)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    db_live = "disconnected"
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        db_live = "connected"
    except Exception as exc:
        db_live = f"error: {exc}"

    from app.ai_providers import get_ordered_provider_chain, _is_provider_configured
    try:
        chain = get_ordered_provider_chain()
        chain_names = [n for n, _ in chain]
        ai_status = f"ready ({chain_names})" if chain_names else "degraded — no providers configured"
    except Exception as exc:
        chain_names = []
        ai_status = f"error: {exc}"

    overall_ok = db_live == "connected" and bool(chain_names)

    return {
        "status":          "ok" if overall_ok else "degraded",
        "version":         "1.0.0",
        "database":        db_live,
        "tables":          _startup["tables"],
        "pgvector":        _startup["pgvector"],
        "vector_search":   _startup["vector_search"],
        "embeddings":      _startup["embedder"],
        "ai_provider":     settings.AI_PROVIDER,
        "ai_chain":        chain_names,
        "ai_status":       ai_status,
        "fix_hint": (
            None if chain_names else
            "No AI providers configured. Add GEMINI_API_KEY (get free at aistudio.google.com) "
            "or OPENAI_API_KEY / ANTHROPIC_API_KEY to backend/.env, then restart. "
            "See GET /api/v1/debug/provider-health for details."
        ),
    }


@app.get("/health/providers")
async def health_providers():
    """Per-provider configuration + active selection. Safe to expose — no key values."""
    from app.ai_providers import (
        _is_provider_configured,
        get_active_provider_name,
        get_provider_health,
    )

    gemini_ok    = _is_provider_configured("gemini")
    openai_ok    = _is_provider_configured("openai")
    anthropic_ok = _is_provider_configured("anthropic")
    active       = get_active_provider_name()

    return {
        "gemini_configured":    gemini_ok,
        "openai_configured":    openai_ok,
        "anthropic_configured": anthropic_ok,
        "active_provider":      active,
        "primary_setting":      settings.AI_PROVIDER,
        "health": {
            "gemini":    get_provider_health("gemini"),
            "openai":    get_provider_health("openai"),
            "anthropic": get_provider_health("anthropic"),
        },
    }
