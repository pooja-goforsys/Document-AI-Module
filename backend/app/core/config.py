from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Literal
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/docai"

    # ── AI Provider ───────────────────────────────────────────────────────────
    AI_PROVIDER: Literal["gemini", "openai", "anthropic", "local"] = "gemini"
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    # GEMINI_MODEL must be a Gemini API identifier (lowercase, hyphenated),
    # not a marketing label like "Gemini 3.1 Flash-Lite". Valid IDs include:
    #   gemini-2.5-flash, gemini-2.0-flash, gemini-2.5-flash-lite,
    #   gemini-flash-latest, gemini-flash-lite-latest
    # A label with spaces/capitals causes the API to return 404 NOT_FOUND on
    # every call, which then falls through to the local chunk-display path.
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-4-7"
    # LOCAL_MODEL_ENDPOINT: Ollama / LM Studio / vLLM endpoint, e.g. http://localhost:11434
    LOCAL_MODEL_ENDPOINT: str = ""
    LOCAL_MODEL_NAME: str = "llama3.2"

    # ── Embedding Provider ────────────────────────────────────────────────────
    EMBEDDING_PROVIDER: Literal["huggingface", "gemini", "openai"] = "huggingface"
    # all-MiniLM-L6-v2: 22M params, 384 dims, ~6× faster than all-mpnet-base-v2
    # on CPU.  Changing this model requires re-indexing all documents because
    # stored embeddings become incompatible (different dimension / vector space).
    HF_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    GEMINI_EMBEDDING_MODEL: str = "models/text-embedding-004"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_VERSION: str = "v1"

    # ── RAG ───────────────────────────────────────────────────────────────────
    SIMILARITY_THRESHOLD: float = 0.65
    # Primary cosine-distance threshold (0 = identical, 1 = orthogonal).
    # dist ≤ 0.65 → similarity ≥ 0.35.  Used for the first retrieval pass.

    SIMILARITY_THRESHOLD_RELAXED: float = 0.82
    # Fallback threshold when the primary pass returns fewer than
    # MIN_RETRIEVAL_RESULTS chunks.  dist ≤ 0.82 → similarity ≥ 0.18.
    # Broader net; catches paraphrases and less direct matches.

    MIN_RETRIEVAL_RESULTS: int = 2
    # Minimum chunk count from the primary pass before triggering the relaxed
    # pass.  If the primary pass returns ≥ this many chunks, no fallback runs.

    # Chunking — sizes are in tiktoken cl100k_base tokens (not characters).
    # all-MiniLM-L6-v2 max context is 256 tokens; chunks larger than that are
    # embedded with automatic tail truncation. Chunk content is sent to the LLM
    # in full regardless of embedding truncation.
    CHUNK_SIZE: int = 1200
    CHUNK_OVERLAP: int = 250
    PDF_EXTRACTOR: str = "auto"  # "auto" | "pdfplumber" | "pymupdf" | "pypdf"

    TOP_K_CHUNKS: int = 5                 # chunks sent to the LLM after reranking
    VECTOR_SEARCH_CANDIDATES: int = 50    # raw candidates fetched from pgvector per variant.
    # Reduced from 100 → 50: fetching 100 candidates per query variant floods the
    # candidate pool with low-quality matches that dilute the cross-encoder's input.
    # 50 is more than enough for high recall; the cross-encoder then cuts to top-K.
    RERANKER_INPUT_SIZE: int = 20         # default candidates fed into the cross-encoder.
    # Intent-aware override applied in stream_response():
    #   focused (oneword/shortfact/person/numerical) → 10
    #   medium  (definition/explanation/process)     → 15
    #   broad   (summary/comparison/analytical)      → 20
    # Lower input means fewer irrelevant chunks in the scoring pool → higher precision.
    MAX_RETRIEVAL_DISTANCE: float = 0.97  # absolute garbage cutoff (sim < 0.03 excluded)
    RETRIEVAL_MIN_RELEVANCE_SCORE: float = 0.35
    RETRIEVAL_DEBUG_ENABLED: bool = False

    # ── Multi-turn conversation ───────────────────────────────────────────────
    CONVERSATION_HISTORY_LIMIT: int = 10  # messages to include in multi-turn context

    # ── Cross-encoder reranking ───────────────────────────────────────────────
    # Applied after bi-encoder retrieval to remove irrelevant chunks.
    #
    # RERANKER_BACKEND controls which scoring engine is used:
    #   "local"  — load a model from Hugging Face (no API key required)
    #   "cohere" — use Cohere Rerank API  (requires COHERE_API_KEY)
    #   "jina"   — use Jina Reranker API  (requires JINA_API_KEY)
    #   "auto"   — try cohere → jina → local in that order
    #
    # RERANKER_MODEL controls which local model is loaded (backend="local"):
    #   BAAI/bge-reranker-v2-m3           — default; 568 M params; excellent on
    #                                        enterprise policy / HR / technical docs;
    #                                        significantly better than ms-marco on
    #                                        within-domain subtopic disambiguation.
    #   cross-encoder/ms-marco-MiniLM-L-6-v2 — 22 M params; faster; weaker on
    #                                        within-domain distinction (web-search
    #                                        training distribution).
    #
    # Score semantics after sigmoid normalisation (applies to all local models):
    #   0.00 – 0.29  very unlikely to answer the question
    #   0.30 – 0.49  borderline — may contain partial information
    #   0.50 – 0.74  likely relevant
    #   0.75 – 1.00  highly relevant, directly answers
    RERANKER_ENABLED: bool = True
    RERANKER_BACKEND: str = "local"                      # "local" | "cohere" | "jina" | "auto"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"  # safer local default; see reranker.py
    COHERE_API_KEY: str = ""                             # for backend="cohere" or "auto"
    JINA_API_KEY: str = ""                               # for backend="jina"  or "auto"
    RERANKER_TOP_K: int = 5           # chunks returned after reranking → sent to LLM
    RERANKER_MIN_SCORE: float = 0.30  # minimum relevance threshold; chunks below this score
    # are excluded unless needed to meet RERANKER_MIN_RESULTS.
    # Raised from 0.25 → 0.30 to reduce low-quality fallback chunks.
    RERANKER_MIN_RESULTS: int = 2     # guaranteed minimum chunks returned even below threshold.
    # Lowered from 5 → 2: prevents forcing 5 irrelevant chunks into LLM context
    # when only 1–2 chunks actually answer the question.
    #
    # Score-gap pruning: cuts the result list at the first large drop in
    # cross-encoder scores (e.g. VPN=0.78 | gap=0.54 | Travel=0.24 → cut).
    # Applied AFTER the threshold filter so min_results is respected first.
    RERANKER_SCORE_GAP_PRUNE: bool = True
    RERANKER_SCORE_GAP_THRESHOLD: float = 0.30  # drop ≥ this between adjacent scores → cut

    # ── Hybrid search ─────────────────────────────────────────────────────────
    HYBRID_SEARCH_ENABLED: bool = True
    HYBRID_SEARCH_KEYWORD_BOOST: float = 0.15  # cosine distance reduction for keyword+vector hits
    HYBRID_SEARCH_RRF_K: int = 60              # reciprocal rank fusion smoothing constant
    MAX_CHUNKS_PER_PAGE: int = 5   # dedup allows this many chunks per (doc_id, page_number)

    # ── Parent-child (context expansion) retrieval ───────────────────────────
    # After the reranker, fetch adjacent section-sibling chunks so the LLM
    # receives full section context (e.g. the full product card when a single
    # feature row matched).
    PARENT_CHILD_EXPANSION_ENABLED: bool = True
    PARENT_CHILD_MAX_SIBLINGS: int = 2    # max extra chunks added per matched section
    PARENT_CHILD_LLM_CAP: int = 10        # max chunks sent to LLM after expansion

    # ── Section metadata boost ────────────────────────────────────────────────
    # Cosine-distance reduction applied to chunks whose section_heading matches
    # the detected query section — raises them in the reranker candidate pool.
    SECTION_METADATA_BOOST: float = 0.12

    # ── Provider health monitoring ────────────────────────────────────────────
    # Seconds before a transiently-failed provider (timeout/5xx) is retried.
    PROVIDER_HEALTH_TTL: int = 300
    # Seconds before a quota-exhausted provider is retried (24 h).
    PROVIDER_QUOTA_TTL: int = 86400

    # ── Retrieval validation ──────────────────────────────────────────────────
    # When True, cross-domain contamination checks run after reranking.
    RETRIEVAL_VALIDATION_ENABLED: bool = True

    # ── Retrieval confidence gate ─────────────────────────────────────────────
    # When True, queries whose retrieved chunks fall below the confidence
    # thresholds below are returned as structured "Not Found" responses
    # without calling the LLM.  This prevents hallucinations on out-of-domain
    # questions (e.g. "CEO favourite colour") where the retrieved chunks are
    # irrelevant noise rather than evidence.
    CONFIDENCE_GATE_ENABLED: bool = True

    # G1 — Absolute noise threshold.
    # If the BEST chunk's similarity score (0-1) is below this value the
    # question is almost certainly out of scope for the indexed documents.
    # Score guide after cross-encoder: 0.25 = very weak signal.
    CONFIDENCE_GATE_ABSOLUTE_MIN: float = 0.25

    # G2 — Composite confidence threshold (0-100).
    # _calculate_confidence() produces a weighted score:
    #   50 % best-chunk sim + 30 % avg sim + 20 % coverage
    # Scores below this value indicate the overall retrieval pool is too
    # noisy to generate a reliable answer.
    CONFIDENCE_GATE_SCORE_MIN: float = 35.0

    # Similarity score above which a chunk is considered "high quality"
    # (directly answers the question rather than being marginally related).
    CONFIDENCE_GATE_HIGH_QUALITY_SIM: float = 0.50

    # ── Document quality checks ───────────────────────────────────────────────
    # When True, warn if uploaded documents contain evaluation/test artifacts.
    CHUNK_CONTAMINATION_CHECK: bool = True

    # ── Debug / failure-mode exposure ─────────────────────────────────────────
    # When False (default), provider-failure responses show a clean message
    # ("Unable to generate an answer at the moment. Please try again.")
    # instead of raw retrieved-chunk excerpts. Source citations (doc + page)
    # are still attached via the sources SSE event so the user can verify.
    # Set DEBUG_MODE=true in .env to surface excerpts during development.
    DEBUG_MODE: bool = False

    # ── File Storage ──────────────────────────────────────────────────────────
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 50

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    SECRET_KEY: str = "CHANGE-THIS-IN-PRODUCTION-USE-A-LONG-RANDOM-SECRET-KEY-MIN-32-CHARS"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    FRONTEND_URL: str = "http://localhost:5173"

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    # Sync URL for Alembic (replaces asyncpg with psycopg2)
    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2")

    def ensure_upload_dir(self):
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)

    @field_validator("GEMINI_MODEL", mode="before")
    @classmethod
    def _normalize_gemini_model(cls, v: object) -> str:
        """Reject marketing labels like 'Gemini 3.1 Flash-Lite'.

        The Gemini API only accepts identifiers in the form
        gemini-<version>-<variant> (lowercase, hyphenated). A label causes
        404 NOT_FOUND on every call which then drops the user into the
        local chunk-display fallback.
        """
        if not isinstance(v, str):
            return v  # let pydantic raise the proper type error
        raw = v.strip()
        if not raw:
            return raw
        looks_like_id = raw.startswith("gemini-") and " " not in raw and raw.lower() == raw
        if looks_like_id:
            return raw
        # Best-effort normalisation: "Gemini 3.1 Flash-Lite" → "gemini-3.1-flash-lite"
        normalized = raw.lower().replace(" ", "-")
        import logging
        logging.getLogger(__name__).warning(
            "[Settings] GEMINI_MODEL=%r looks like a marketing label, not an API id. "
            "Normalized to %r. Set a valid id (e.g. gemini-2.5-flash) in backend/.env "
            "to silence this warning.",
            raw, normalized,
        )
        return normalized


settings = Settings()
settings.ensure_upload_dir()
