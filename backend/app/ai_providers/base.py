from abc import ABC, abstractmethod
from typing import AsyncGenerator


class BaseAIProvider(ABC):
    @abstractmethod
    async def stream_chat(
        self,
        system_prompt: str,
        question: str,
        context: str,
        conversation_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Yield text tokens as an async generator.

        Parameters
        ----------
        system_prompt : str
            The system/instruction prompt (scope header + mode instruction + base rules).
        question : str
            The current user question.
        context : str
            The formatted <context>…</context> block built from retrieved chunks.
        conversation_history : list[dict] | None
            Optional list of prior turns: [{"role": "user"|"assistant", "content": str}, …]
            Ordered oldest-first. Used to build multi-turn conversation context.
        """
        yield ""
