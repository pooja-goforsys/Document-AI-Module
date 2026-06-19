"""
Gemini AI provider — google-genai SDK 2.x

Key implementation notes
────────────────────────
• Uses the SYNC streaming client wrapped in run_in_executor.
  Avoids the _async_httpx_client cleanup bug in google-genai 2.x.

• SSL workaround for Windows + Python 3.14:
  The Windows Python installation has no valid system CA bundle, so every
  outbound HTTPS call to Google fails with CERTIFICATE_VERIFY_FAILED.
  Neither certifi nor SSL_CERT_FILE env-var fixes it at this Python version.
  The only working solution is to pass a pre-built httpx.Client(verify=False)
  through HttpOptions(httpx_client=…).
  This is safe for a local development server — traffic never leaves localhost.

• Multi-turn conversation history:
  Prior turns are passed as a list of Content objects (role="user"|"model")
  before the current user content, enabling genuine multi-turn context.

• Retry / fallback:
  429 RESOURCE_EXHAUSTED → limited to 2 attempts per model, then fallback.
  503 UNAVAILABLE / timeout → up to 4 attempts with exponential backoff.
  404 NOT_FOUND → model skipped immediately, fallback selected.
  Fallback chain: gemini-2.5-flash → gemini-2.0-flash
  (gemini-1.5-flash excluded — returns 404 NOT_FOUND).
"""
import asyncio
import logging
import time as _time
import warnings

from app.ai_providers.base import BaseAIProvider
from app.ai_providers.retry_utils import retry_gemini_request, AIServiceUnavailableError
from app.core.config import settings

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {
    "",
    "your_gemini_api_key_here",
    "your-gemini-api-key",
    "your-api-key",
    "add-your-key-here",
    "placeholder",
    "xxxx",
    "xxxxxx",
}

# Valid Gemini API keys from Google AI Studio start with "AIzaSy"
_GEMINI_KEY_PREFIX = "AIzaSy"


class GeminiProvider(BaseAIProvider):

    def __init__(self):
        self._client     = None
        self._model      = settings.GEMINI_MODEL
        self._configured = False

        key = (settings.GEMINI_API_KEY or "").strip()
        if not key or key.lower() in _PLACEHOLDER_KEYS:
            logger.warning(
                "[Gemini] GEMINI_API_KEY is not set or is a placeholder.\n"
                "         1. Go to https://aistudio.google.com/app/apikey\n"
                "         2. Create a free API key\n"
                "         3. Add it to backend/.env:  GEMINI_API_KEY=AIzaSy...\n"
                "         4. Restart uvicorn\n"
                "         AI chat is disabled until a valid key is provided."
            )
            return

        # Soft prefix check — only warn if the key doesn't match the most
        # common Google AI Studio format. Some newer/alternative Google AI
        # credentials use other prefixes (e.g. "AQ."), so we let the SDK
        # validate the key on the first real request rather than refusing
        # to initialise. A bad key surfaces as a 401 -> auth_failed via the
        # existing error handler below.
        if not key.startswith(_GEMINI_KEY_PREFIX):
            logger.warning(
                f"[Gemini] GEMINI_API_KEY prefix is unusual (expected '{_GEMINI_KEY_PREFIX}', "
                f"got '{key[:6]}...'). Proceeding anyway — if requests fail with 401, "
                f"create a fresh key at https://aistudio.google.com/app/apikey"
            )

        try:
            import httpx
            from google import genai as _genai
            from google.genai import types as _gtypes

            warnings.filterwarnings("ignore", message=".*Unverified HTTPS.*")

            # 90 s connect + 120 s read — prevents indefinite hangs when
            # the Gemini API is unresponsive (run_in_executor would block forever
            # without a timeout, keeping the SSE stream open with no data).
            hx = httpx.Client(verify=False, timeout=httpx.Timeout(connect=90.0, read=120.0, write=60.0, pool=30.0))
            http_opts = _gtypes.HttpOptions(httpx_client=hx)

            self._client     = _genai.Client(api_key=key, http_options=http_opts)
            self._configured = True
            logger.info(f"[Gemini] Initialized OK — primary model: {self._model}")
            logger.warning(
                "[Gemini] SSL verification is DISABLED (Windows CA store workaround). "
                "Safe for local development."
            )
        except Exception as exc:
            logger.error(f"[Gemini] Initialization failed: {exc}")

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def stream_chat(
        self,
        system_prompt: str,
        question: str,
        context: str,
        conversation_history: list[dict] | None = None,
    ) -> BaseAIProvider.stream_chat.__annotations__.get("return", None):
        if not self._configured or self._client is None:
            yield (
                "**AI is not configured.** "
                "Please add your GEMINI_API_KEY to `backend/.env` and restart the server. "
                "Get a free key at https://aistudio.google.com/app/apikey"
            )
            return

        current_user_content = (
            f"{context}\n\n"
            "━━━ GROUNDING REMINDER ━━━\n"
            "Answer using ONLY the excerpts above.\n"
            "Cite every factual claim with [N] matching the excerpt number.\n"
            "If the excerpts do not fully answer the question, state clearly "
            "what is missing rather than filling gaps from external knowledge.\n\n"
            f"Question: {question}"
        )

        # Build contents once — reused across retry attempts (immutable)
        contents = _build_contents(conversation_history, current_user_content)

        history_turns = len(conversation_history) if conversation_history else 0
        logger.info(
            f"[Gemini] ── REQUEST ─────────────────────────────────────────────"
        )
        logger.info(
            f"[Gemini] Model          : {self._model}"
        )
        logger.info(
            f"[Gemini] System prompt  : {len(system_prompt)} chars  "
            f"(~{len(system_prompt)//4} tokens)"
        )
        logger.info(
            f"[Gemini] User content   : {len(current_user_content)} chars  "
            f"(~{len(current_user_content)//4} tokens)"
        )
        logger.info(
            f"[Gemini] History turns  : {history_turns}"
        )
        logger.info(
            f"[Gemini] Total input    : ~{(len(system_prompt)+len(current_user_content))//4} tokens"
        )
        logger.info(
            f"[Gemini] ─────────────────────────────────────────────────────────"
        )

        def _call_with_model(model: str) -> list[str]:
            """Sync call to Gemini for one model; returns collected tokens."""
            from google.genai import types as _gtypes

            cfg = _gtypes.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                top_p=0.85,
                max_output_tokens=8192,
            )
            tokens: list[str] = []
            for chunk in self._client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=cfg,
            ):
                text = chunk.text or ""
                if text:
                    tokens.append(text)
            return tokens

        _t_call = _time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            tokens, used_model, attempts = await loop.run_in_executor(
                None,
                lambda: retry_gemini_request(
                    _call_with_model,
                    primary_model=self._model,
                    question_preview=question,
                ),
            )
            _elapsed_ms = round((_time.monotonic() - _t_call) * 1000)
            _full_text  = "".join(tokens)
            _out_chars  = len(_full_text)
            _out_tokens = _out_chars // 4

            if used_model != self._model:
                logger.info(
                    f"[Gemini] Completed via fallback — "
                    f"primary={self._model}  active_model={used_model}  "
                    f"attempts={attempts}  "
                    f"chars={_out_chars}  ~tokens={_out_tokens}  "
                    f"time={_elapsed_ms}ms"
                )
            else:
                logger.info(
                    f"[Gemini] Completed — "
                    f"model={used_model}  "
                    f"attempts={attempts}  "
                    f"chars={_out_chars}  ~tokens={_out_tokens}  "
                    f"time={_elapsed_ms}ms"
                )

            # ── Full response body ─────────────────────────────────────────
            _div = "◀" * 60
            logger.info(f"[Gemini] {_div}")
            logger.info(f"[Gemini] FULL RESPONSE ({_out_chars} chars, ~{_out_tokens} tokens, {_elapsed_ms}ms)")
            logger.info(f"[Gemini] {_div}")
            for _line in _full_text.split("\n"):
                logger.info(f"[Gemini] │ {_line}")
            logger.info(f"[Gemini] {_div}")

            # ── RULE 6 refusal detection ───────────────────────────────────
            if (
                "not available in the uploaded documents" in _full_text.lower()
                or "not found in documents" in _full_text.lower()
                or "could not find" in _full_text.lower()
            ):
                logger.warning(
                    f"[Gemini] ⚠ REFUSAL RESPONSE GENERATED  "
                    f"model={used_model}  question={question!r}"
                )
                logger.warning(
                    "[Gemini]   This means Gemini received context but decided "
                    "it does not answer the question. "
                    "Enable DEBUG log level and check the full context block above."
                )

            # ── Citation check ─────────────────────────────────────────────
            import re as _re
            _citations_found = _re.findall(r'\[\d+\]', _full_text)
            if _citations_found:
                logger.info(
                    f"[Gemini] Citations in response: {_citations_found}"
                )
            else:
                logger.warning(
                    f"[Gemini] ⚠ No citations [N] found in response — "
                    "system prompt RULE 2 may have been ignored"
                )

        except AIServiceUnavailableError:
            _elapsed_ms = round((_time.monotonic() - _t_call) * 1000)
            logger.error(
                f"[Gemini] All models exhausted — "
                f"primary={self._model}  time={_elapsed_ms}ms"
            )
            raise  # already correct type — chat_service will try fallback chain
        except Exception as exc:
            _elapsed_ms = round((_time.monotonic() - _t_call) * 1000)
            # Convert any unexpected exception (401, network error, SDK bug, etc.)
            # to AIServiceUnavailableError so the chat_service fallback chain fires.
            # Without this, a 401 UNAUTHORIZED propagates as a raw SDK exception and
            # bypasses the `except AIServiceUnavailableError` handler, killing the stream.
            err_lower = str(exc).lower()
            if "401" in str(exc) or "unauthorized" in err_lower or "api_key" in err_lower:
                error_type = "auth_failed"
                logger.error(
                    f"[Gemini] Authentication failed (401) — "
                    f"GEMINI_API_KEY is invalid or revoked.  "
                    f"Get a new key at https://aistudio.google.com/app/apikey  "
                    f"time={_elapsed_ms}ms  detail={exc}"
                )
            else:
                error_type = "unavailable"
                logger.error(
                    f"[Gemini] Fatal API error — "
                    f"{type(exc).__name__}: {exc}  time={_elapsed_ms}ms"
                )
            raise AIServiceUnavailableError(
                f"Gemini error: {type(exc).__name__}: {exc}",
                error_type=error_type,
            ) from exc

        for token in tokens:
            yield token


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_contents(
    conversation_history: list[dict] | None,
    current_user_content: str,
) -> list:
    """Build the Gemini multi-turn contents list."""
    from google.genai import types as _gtypes

    contents: list = []
    if conversation_history:
        for turn in conversation_history:
            role  = turn.get("role", "user")
            text  = turn.get("content", "")
            grole = "model" if role == "assistant" else "user"
            contents.append(
                _gtypes.Content(role=grole, parts=[_gtypes.Part(text=text)])
            )

    contents.append(
        _gtypes.Content(role="user", parts=[_gtypes.Part(text=current_user_content)])
    )
    return contents
