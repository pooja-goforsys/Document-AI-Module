"""
pgvector availability flag.

Set once at startup (main.py) via set_available().
Read by _retrieve_chunks() to enable native SQL ORDER BY <=> instead of
Python-side cosine over all embeddings.
"""

_available: bool = False


def set_available(enabled: bool) -> None:
    global _available
    _available = enabled


def is_available() -> bool:
    return _available
