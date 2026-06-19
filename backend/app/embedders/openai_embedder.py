from app.embedders.base import BaseEmbedder
from app.core.config import settings


class OpenAIEmbedder(BaseEmbedder):
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model  = settings.OPENAI_EMBEDDING_MODEL

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    async def embed_query(self, text: str) -> list[float]:
        result = await self.embed_texts([text])
        return result[0]
