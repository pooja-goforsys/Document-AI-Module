"""
Local model provider — OpenAI-compatible API (Ollama, LM Studio, vLLM).
Set LOCAL_MODEL_ENDPOINT in backend/.env, e.g.:
  LOCAL_MODEL_ENDPOINT=http://localhost:11434
  LOCAL_MODEL_NAME=llama3.2
"""
import logging
from app.ai_providers.base import BaseAIProvider
from app.ai_providers.retry_utils import AIServiceUnavailableError
from app.core.config import settings

logger = logging.getLogger(__name__)


class LocalProvider(BaseAIProvider):

    def __init__(self):
        self._client     = None
        self._configured = False
        self._model      = settings.LOCAL_MODEL_NAME

        endpoint = (settings.LOCAL_MODEL_ENDPOINT or "").strip()
        if not endpoint:
            return

        try:
            from openai import AsyncOpenAI
            self._client     = AsyncOpenAI(
                base_url=f"{endpoint.rstrip('/')}/v1",
                api_key="local",  # Ollama does not require a key
            )
            self._configured = True
            logger.info(
                f"[Local] Initialized OK — endpoint={endpoint}  model={self._model}"
            )
        except Exception as exc:
            logger.error(f"[Local] Initialization failed: {exc}")

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def stream_chat(
        self,
        system_prompt: str,
        question: str,
        context: str,
        conversation_history: list[dict] | None = None,
    ):
        if not self._configured or self._client is None:
            raise AIServiceUnavailableError(
                "Local model endpoint not configured", error_type="not_configured"
            )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({
            "role": "user",
            "content": (
                f"{context}\n\n"
                "Answer using ONLY the excerpts above. "
                "Cite every factual claim with [N].\n\n"
                f"Question: {question}"
            ),
        })

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
            logger.info(f"[Local] Response completed — model={self._model}")
        except Exception as exc:
            logger.error(f"[Local] API error: {type(exc).__name__}: {exc}")
            raise AIServiceUnavailableError(str(exc), error_type="unavailable") from exc
