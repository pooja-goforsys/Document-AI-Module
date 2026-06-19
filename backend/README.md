# Document AI — Backend

Production-grade RAG API built with FastAPI + PostgreSQL + pgvector.

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ with the `pgvector` extension
- A Gemini API key (or OpenAI key)

## Setup

```bash
# 1. Create & activate virtualenv
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL and GEMINI_API_KEY (or OPENAI_API_KEY)

# 4. Create the database (psql)
createdb docai

# 5. Run migrations
alembic upgrade head

# 6. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v1/folders/ | List folders |
| POST | /api/v1/folders/ | Create folder |
| PATCH | /api/v1/folders/{id} | Rename folder |
| DELETE | /api/v1/folders/{id} | Delete folder |
| POST | /api/v1/documents/upload | Upload & index document |
| GET | /api/v1/documents/ | List documents |
| DELETE | /api/v1/documents/{id} | Delete document |
| POST | /api/v1/documents/{id}/reindex | Re-index document |
| GET | /api/v1/chat/sessions | List chat sessions |
| POST | /api/v1/chat/sessions | Create session |
| GET | /api/v1/chat/sessions/{id}/messages | Get messages |
| POST | /api/v1/chat/query | Stream chat (SSE) |
| DELETE | /api/v1/chat/sessions/{id} | Delete session |
| GET | /api/v1/stats | Dashboard stats |
| GET | /api/v1/queries/recent | Recent queries |
| GET | /health | Health check |

## SSE Chat Format

The chat endpoint streams `text/event-stream`:

```
event: token
data: {"text": "..."}

event: sources
data: {"sources": [...], "success": true, "session_id": "uuid"}

event: done
data: {"session_id": "uuid"}

event: error
data: {"message": "..."}
```

## Architecture

```
Request → Router → Service → (Embedder + pgvector + LLM) → SSE stream
```
