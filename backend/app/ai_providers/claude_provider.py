"""
Anthropic Claude provider — anthropic SDK async streaming.
"""
import logging
from app.ai_providers.base import BaseAIProvider
from app.ai_providers.retry_utils import AIServiceUnavailableError
from app.core.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = frozenset({
    "", "your_anthropic_api_key_here", "your-anthropic-api-key",
    "your-api-key", "add-your-key-here", "placeholder", "xxxx",
})


class ClaudeProvider(BaseAIProvider):

    def __init__(self):
        self._client     = None
        self._configured = False
        self._model      = settings.ANTHROPIC_MODEL

        key = (settings.ANTHROPIC_API_KEY or "").strip()
        if not key or key.lower() in _PLACEHOLDER_KEYS:
            logger.warning(
                "[Claude] ANTHROPIC_API_KEY is not set — Claude provider disabled.\n"
                "         Set ANTHROPIC_API_KEY in backend/.env to enable."
            )
            return

        try:
            import anthropic
            self._client     = anthropic.AsyncAnthropic(api_key=key)
            self._configured = True
            logger.info(f"[Claude] Initialized OK — model: {self._model}")
        except ImportError:
            logger.error(
                "[Claude] 'anthropic' package not installed. "
                "Run: pip install anthropic>=0.40.0"
            )
        except Exception as exc:
            logger.error(f"[Claude] Initialization failed: {exc}")

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
                "Anthropic API key not configured", error_type="not_configured"
            )

        messages: list[dict] = []
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({
            "role": "user",
            "content": (
                f"{context}\n\n"
                "━━━ GROUNDING REMINDER ━━━\n"
                "Answer using ONLY the excerpts above.\n"
                "Cite every factual claim with [N].\n\n"
                f"Question: {question}"
            ),
        })

        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
            logger.info(f"[Claude] Response completed — model={self._model}")
        except Exception as exc:
            logger.error(f"[Claude] API error: {type(exc).__name__}: {exc}")
            raise AIServiceUnavailableError(str(exc), error_type="unavailable") from exc
