import asyncio
from app.embedders.base import BaseEmbedder
from app.core.config import settings


class GeminiEmbedder(BaseEmbedder):
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._genai = genai
        self._model = settings.GEMINI_EMBEDDING_MODEL

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()

        # Run all embed_content calls concurrently in the thread pool.
        # The previous implementation issued one sequential executor call per
        # text, so a batch of 64 chunks = 64 round-trips done one after another.
        # asyncio.gather submits them all simultaneously and waits for the
        # slowest one, cutting wall-clock time from O(N) → O(1) per batch.
        def _embed_one(text: str) -> list[float]:
            return self._genai.embed_content(
                model=self._model, content=text
            )["embedding"]

        tasks = [
            loop.run_in_executor(None, _embed_one, t)
            for t in texts
        ]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def embed_query(self, text: str) -> list[float]:
        result = await self.embed_texts([text])
        return result[0]
