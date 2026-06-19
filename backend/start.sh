#!/usr/bin/env bash
# Starts the FastAPI backend with uvicorn.
# Run from the backend/ directory: bash start.sh

set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "[!] No .env found — copying from .env.example"
  cp .env.example .env
fi

# Run Alembic migrations
echo "[*] Running migrations…"
python -m alembic upgrade head

# Start server
echo "[*] Starting server on http://localhost:8000"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
