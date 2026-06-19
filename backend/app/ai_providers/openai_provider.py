import logging
import time as _time
from typing import AsyncGenerator
from app.ai_providers.base import BaseAIProvider
from app.ai_providers.retry_utils import AIServiceUnavailableError
from app.core.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = frozenset({
    "", "your_openai_api_key_here", "your-openai-api-key",
    "your-api-key", "add-your-key-here", "placeholder", "xxxx", "sk-placeholder",
})


class OpenAIProvider(BaseAIProvider):
    def __init__(self):
        self._configured = False
        key = (settings.OPENAI_API_KEY or "").strip()
        if not key or key.lower() in _PLACEHOLDER_KEYS:
            logger.warning(
                "[OpenAI] OPENAI_API_KEY is not set or is a placeholder. "
                "Add it to backend/.env: OPENAI_API_KEY=sk-..."
            )
            self.client = None
            return
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            self._configured = True
            logger.info(f"[OpenAI] Initialized OK — model: {settings.OPENAI_MODEL}")
        except Exception as exc:
            logger.error(f"[OpenAI] Initialization failed: {exc}")
            self.client = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def stream_chat(
        self,
        system_prompt: str,
        question: str,
        context: str,
        conversation_history: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        if not self._configured or self.client is None:
            yield (
                "**AI is not configured.** "
                "Please add your OPENAI_API_KEY to `backend/.env` and restart the server."
            )
            return

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for turn in conversation_history:
                role    = turn.get("role", "user")
                content = turn.get("content", "")
                messages.append({"role": role, "content": content})

        messages.append({
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {question}",
        })

        history_turns = len(conversation_history) if conversation_history else 0
        total_input_chars = len(system_prompt) + len(context) + len(question)

        logger.info("[OpenAI] ── REQUEST ─────────────────────────────────────────────")
        logger.info(f"[OpenAI] Model          : {settings.OPENAI_MODEL}")
        logger.info(f"[OpenAI] System prompt  : {len(system_prompt)} chars  (~{len(system_prompt)//4} tokens)")
        logger.info(f"[OpenAI] Context        : {len(context)} chars  (~{len(context)//4} tokens)")
        logger.info(f"[OpenAI] History turns  : {history_turns}")
        logger.info(f"[OpenAI] Total input    : ~{total_input_chars//4} tokens")
        logger.info("[OpenAI] ─────────────────────────────────────────────────────────")

        _t_start = _time.monotonic()
        collected: list[str] = []

        try:
            async with self.client.chat.completions.stream(
                model=settings.OPENAI_MODEL,
                messages=messages,
                temperature=0.0,
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        collected.append(text)
                        yield text

            _elapsed_ms  = round((_time.monotonic() - _t_start) * 1000)
            _full_text   = "".join(collected)
            _out_tokens  = len(_full_text) // 4

            logger.info(
                f"[OpenAI] Completed — model={settings.OPENAI_MODEL}  "
                f"chars={len(_full_text)}  ~tokens={_out_tokens}  time={_elapsed_ms}ms"
            )

        except Exception as exc:
            _elapsed_ms = round((_time.monotonic() - _t_start) * 1000)
            exc_str     = str(exc)
            exc_lower   = exc_str.lower()
            exc_type    = type(exc).__name__

            # ── Classify the error ────────────────────────────────────────────
            if (
                "401" in exc_str
                or "authentication" in exc_lower
                or "invalid_api_key" in exc_lower
                or "incorrect api key" in exc_lower
            ):
                error_type = "auth_failed"
                logger.error(
                    f"[OpenAI] Authentication failed (401) — "
                    f"OPENAI_API_KEY is invalid or revoked.  "
                    f"Get a new key at https://platform.openai.com/api-keys  "
                    f"time={_elapsed_ms}ms  detail={exc}"
                )
            elif (
                "429" in exc_str
                or "rate_limit" in exc_lower
                or "quota" in exc_lower
                or "insufficient_quota" in exc_lower
                or "too many requests" in exc_lower
            ):
                error_type = "quota_exceeded"
                logger.warning(
                    f"[OpenAI] Rate limit / quota exceeded (429) — "
                    f"time={_elapsed_ms}ms  detail={exc}"
                )
            elif (
                "timeout" in exc_lower
                or "503" in exc_str
                or "service unavailable" in exc_lower
                or "connection" in exc_lower
            ):
                error_type = "unavailable"
                logger.error(
                    f"[OpenAI] Service unavailable / timeout — "
                    f"{exc_type}: {exc}  time={_elapsed_ms}ms"
                )
            else:
                error_type = "unavailable"
                logger.error(
                    f"[OpenAI] API error — {exc_type}: {exc}  time={_elapsed_ms}ms"
                )

            raise AIServiceUnavailableError(
                f"OpenAI error ({error_type}): {exc_type}: {exc}",
                error_type=error_type,
            ) from exc
