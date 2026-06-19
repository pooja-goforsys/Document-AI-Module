import asyncio
import logging
import math
import time as _time
from app.embedders.base import BaseEmbedder
from app.core.config import settings

logger = logging.getLogger(__name__)


class HuggingFaceEmbedder(BaseEmbedder):
    _model = None

    @classmethod
    def _load_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer
            # Try loading normally first (downloads model if not cached).
            # If the network is unavailable (SSL error, firewall, offline dev
            # machine), fall back to the local HuggingFace cache so that an
            # already-cached model still works without internet access.
            try:
                cls._model = SentenceTransformer(settings.HF_EMBEDDING_MODEL)
            except Exception as first_exc:
                logger.warning(
                    f"[HuggingFaceEmbedder] Online load failed ({first_exc!r}), "
                    "retrying from local cache (local_files_only=True)"
                )
                cls._model = SentenceTransformer(
                    settings.HF_EMBEDDING_MODEL,
                    local_files_only=True,
                )
            logger.info(
                f"[HuggingFaceEmbedder] Loaded model: {settings.HF_EMBEDDING_MODEL}"
            )
        return cls._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()

        # Run encoding in a thread executor so it never blocks the event loop.
        # batch_size=64 matches EMBED_BATCH_SIZE in indexing_task.py — tells
        # SentenceTransformers how large each GPU/CPU mini-batch should be.
        def _encode():
            model = self._load_model()
            return model.encode(
                texts,
                batch_size=64,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

        _t0   = _time.monotonic()
        vecs  = await loop.run_in_executor(None, _encode)
        _ms   = round((_time.monotonic() - _t0) * 1000)
        _list = vecs.tolist()

        if _list:
            _v0  = _list[0]
            _mag = math.sqrt(sum(_x * _x for _x in _v0))
            logger.debug(
                f"[Embedder] embed_texts  "
                f"count={len(_list)}  dim={len(_v0)}  "
                f"magnitude={_mag:.4f}  time={_ms}ms"
            )
            if len(_v0) != 384:
                logger.error(
                    f"[Embedder] DIM MISMATCH — "
                    f"produced={len(_v0)}  expected=384  "
                    "All cosine distances will be wrong. "
                    "Check HF_EMBEDDING_MODEL in config."
                )

        return _list

    async def embed_query(self, text: str) -> list[float]:
        _t0     = _time.monotonic()
        result  = await self.embed_texts([text])
        _ms     = round((_time.monotonic() - _t0) * 1000)
        _vec    = result[0]
        _mag    = math.sqrt(sum(_x * _x for _x in _vec))
        logger.info(
            f"[Embedder] embed_query  "
            f"dim={len(_vec)}  magnitude={_mag:.4f}  time={_ms}ms  "
            f"query={text[:80]!r}"
        )
        return _vec
