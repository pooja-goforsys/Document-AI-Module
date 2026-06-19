from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
