"""
Retry and model-fallback utilities for the Gemini AI provider.

Strategy
────────
Primary model    : up to 4 attempts for transient errors (503/timeout).
                   Only 2 attempts for quota errors (429) before skipping.
Fallback models  : 1 attempt each — no additional retries on fallbacks.
Model not found  : 404 NOT_FOUND → skip immediately to next model, never retry.
Fatal errors     : 401, 400, malformed request → re-raise immediately.

Fallback chain
──────────────
gemini-2.5-flash  (primary, set via GEMINI_MODEL in .env)
gemini-2.0-flash  (first fallback)

gemini-1.5-flash is NOT included — it returns 404 NOT_FOUND.

Error classification
────────────────────
quota          → 429 RESOURCE_EXHAUSTED   — soft cap, limited retries
model_not_found→ 404 NOT_FOUND            — skip immediately, no retries
retryable      → 503 UNAVAILABLE, timeout — up to 4 attempts with backoff
fatal          → 401, 400, unknown        — raise immediately
"""
import time
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Retry schedules ────────────────────────────────────────────────────────────
# Transient errors (503 / timeout): standard exponential backoff
RETRY_DELAYS_TRANSIENT: tuple[int, ...] = (0, 2, 5, 10)
# Quota errors (429): shorter schedule, max 2 attempts then move on
RETRY_DELAYS_QUOTA: tuple[int, ...] = (0, 5)

# ── Supported Gemini models — only models verified to exist ───────────────────
# gemini-1.5-flash is excluded: returns 404 NOT_FOUND (deprecated).
# If GEMINI_MODEL in .env is set to gemini-1.5-flash, the 404 is caught and
# skipped automatically, then gemini-2.5-flash is tried as the first fallback.
# Recommended: set GEMINI_MODEL=gemini-2.0-flash in backend/.env.
FALLBACK_MODEL_CHAIN: list[str] = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]

# ── Error fingerprints ────────────────────────────────────────────────────────
_QUOTA_CODES        = {"429", "RESOURCE_EXHAUSTED"}
_QUOTA_KEYWORDS     = {
    "resource_exhausted", "quota", "rate limit", "too many requests",
    "ratelimit", "rate_limit_exceeded", "user_rate_limit", "daily_limit",
}
_UNAVAILABLE_CODES   = {"503"}
_UNAVAILABLE_KEYWORDS = {
    "unavailable", "service unavailable", "overloaded", "backend error",
    "timeout", "timed out", "connection reset", "connection error",
    "eof", "temporarily unavailable",
}
_NOT_FOUND_CODES    = {"404", "NOT_FOUND"}
_NOT_FOUND_KEYWORDS = {"not found", "does not exist", "model not found", "model_not_found"}


# ── Custom exceptions ─────────────────────────────────────────────────────────

class AIServiceUnavailableError(Exception):
    """
    Raised when all retry attempts and model fallbacks are exhausted.

    Attributes
    ----------
    error_type : "quota_exceeded" | "unavailable"
        "quota_exceeded" — all failures were 429 quota errors.
        "unavailable"    — service down, model not found, or mixed failures.
    """
    def __init__(self, message: str, error_type: str = "unavailable"):
        super().__init__(message)
        self.error_type = error_type


# ── Error classifier ──────────────────────────────────────────────────────────

def classify_error(exc: Exception) -> str:
    """
    Classify an exception into one of four categories.

    Returns
    -------
    "quota"          → 429 RESOURCE_EXHAUSTED  — limited retries allowed
    "model_not_found"→ 404 NOT_FOUND           — skip model immediately
    "retryable"      → 503 / timeout / network — standard backoff retry
    "fatal"          → auth, bad-request, etc. — re-raise immediately
    """
    # ── google-genai 2.x typed exceptions (highest priority) ─────────────────
    try:
        from google.genai import errors as _ge
        if hasattr(_ge, "ClientError") and isinstance(exc, _ge.ClientError):
            code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if code == 429:
                return "quota"
            if code == 404:
                return "model_not_found"
            # 400 / 401 / other 4xx → fatal
            if isinstance(code, int) and 400 <= code < 500:
                return "fatal"
        if hasattr(_ge, "ServerError") and isinstance(exc, _ge.ServerError):
            code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if code == 503:
                return "retryable"
    except ImportError:
        pass

    # ── google.api_core typed exceptions ──────────────────────────────────────
    try:
        from google.api_core import exceptions as _gae
        if isinstance(exc, _gae.ResourceExhausted):
            return "quota"
        if isinstance(exc, _gae.NotFound):
            return "model_not_found"
        if isinstance(exc, (_gae.ServiceUnavailable, _gae.DeadlineExceeded)):
            return "retryable"
    except ImportError:
        pass

    # ── String-based classification (works for any SDK / error format) ────────
    exc_str   = str(exc)
    exc_lower = exc_str.lower()

    if any(code in exc_str for code in _QUOTA_CODES) or \
       any(kw in exc_lower for kw in _QUOTA_KEYWORDS):
        return "quota"

    if any(code in exc_str for code in _NOT_FOUND_CODES) or \
       any(kw in exc_lower for kw in _NOT_FOUND_KEYWORDS):
        return "model_not_found"

    if any(code in exc_str for code in _UNAVAILABLE_CODES) or \
       any(kw in exc_lower for kw in _UNAVAILABLE_KEYWORDS):
        return "retryable"

    return "fatal"


# ── Core retry helper ─────────────────────────────────────────────────────────

def retry_gemini_request(
    call_fn: Callable[[str], Any],
    primary_model: str,
    question_preview: str = "",
) -> tuple[Any, str, int]:
    """
    Execute ``call_fn(model_name)`` with automatic retry and model fallback.

    Parameters
    ----------
    call_fn         : Synchronous callable that takes a model name and returns tokens.
                      Must be synchronous (called inside run_in_executor).
    primary_model   : Model to try first; normally from settings.GEMINI_MODEL.
    question_preview: First ≤80 chars of the question, used only in log messages.

    Returns
    -------
    (result, model_used, total_attempts)

    Raises
    ------
    AIServiceUnavailableError  — all retries and fallbacks exhausted.
                                 Check exc.error_type: "quota_exceeded" | "unavailable".
    Exception                  — fatal (non-retryable) error, re-raised immediately.
    """
    # Build candidate list: primary first, then fallbacks not equal to it
    candidates: list[str] = [primary_model]
    for fb in FALLBACK_MODEL_CHAIN:
        if fb not in candidates:
            candidates.append(fb)

    total_attempts  = 0
    last_error: Exception | None = None
    failure_types: list[str] = []   # "quota" | "model_not_found" | "retryable"
    q_preview = question_preview[:80].replace("\n", " ")

    logger.info(
        f"[AI] Starting request — primary={primary_model}  "
        f"candidates={candidates}  q={q_preview!r}"
    )

    for model_idx, model in enumerate(candidates):
        is_primary = model_idx == 0

        if not is_primary:
            logger.info(
                f"[AI] Fallback selected: {model}  "
                f"(primary={candidates[0]} exhausted)  "
                f"failure_types_so_far={failure_types}"
            )

        # Decide retry schedule and max attempts for this model
        retry_delays  = RETRY_DELAYS_TRANSIENT
        max_attempts  = len(RETRY_DELAYS_TRANSIENT)   # 4 for primary transient
        if not is_primary:
            max_attempts = 1   # fallback models: one shot

        attempt_in_model = 0
        while attempt_in_model < max_attempts:
            if attempt_in_model > 0:
                delay = retry_delays[attempt_in_model]
                logger.info(
                    f"[AI] Waiting {delay}s before retry "
                    f"{attempt_in_model}/{max_attempts - 1}  model={model}"
                )
                time.sleep(delay)

            total_attempts += 1
            logger.info(
                f"[AI] Attempt {total_attempts}  model={model}  "
                f"in_model_attempt={attempt_in_model + 1}/{max_attempts}  "
                f"q={q_preview!r}"
            )

            try:
                result = call_fn(model)
                _log_success(candidates[0], model, total_attempts)
                return result, model, total_attempts

            except Exception as exc:
                err_type = classify_error(exc)
                last_error = exc

                if err_type == "model_not_found":
                    logger.error(
                        f"[AI] Model not found (404): {model} — "
                        f"this model may have been deprecated or is not available on your plan.  "
                        f"attempt={total_attempts}  error={type(exc).__name__}: {exc}"
                    )
                    failure_types.append("model_not_found")
                    break  # skip to next model immediately

                elif err_type == "quota":
                    failure_types.append("quota")
                    logger.warning(
                        f"[AI] Quota/rate-limit (429) on attempt {total_attempts}  "
                        f"model={model}  "
                        f"retry_count_for_model={attempt_in_model}  "
                        f"error={type(exc).__name__}: {exc}"
                    )
                    # Switch to quota schedule and cap at RETRY_DELAYS_QUOTA length
                    retry_delays = RETRY_DELAYS_QUOTA
                    max_attempts_quota = len(RETRY_DELAYS_QUOTA)
                    if attempt_in_model + 1 >= max_attempts_quota:
                        logger.warning(
                            f"[AI] Quota retry cap ({max_attempts_quota} attempts) "
                            f"reached for {model}. Moving to next candidate."
                        )
                        break
                    max_attempts = max_attempts_quota  # tighten remaining budget

                elif err_type == "retryable":
                    failure_types.append("retryable")
                    logger.warning(
                        f"[AI] Transient error (503/timeout) on attempt {total_attempts}  "
                        f"model={model}  "
                        f"retry_count_for_model={attempt_in_model}  "
                        f"error={type(exc).__name__}: {exc}"
                    )
                    if not is_primary:
                        # Fallback models get one shot — don't retry transient on fallback
                        logger.info(
                            f"[AI] Fallback {model} transient error — "
                            f"skipping to next candidate."
                        )
                        break

                else:  # fatal
                    failure_types.append("fatal")
                    logger.error(
                        f"[AI] Fatal (non-retryable) error on attempt {total_attempts}  "
                        f"model={model}  error={type(exc).__name__}: {exc}"
                    )
                    # Wrap as AIServiceUnavailableError so chat_service's failover
                    # chain fires instead of crashing the SSE stream with a raw
                    # SDK exception (e.g. 401 UNAUTHORIZED from a wrong API key).
                    raise AIServiceUnavailableError(
                        f"Fatal error on {model}: {type(exc).__name__}: {exc}",
                        error_type="unavailable",
                    ) from exc

            attempt_in_model += 1

        logger.warning(
            f"[AI] Model {model} exhausted.  "
            f"failure_types={failure_types}  total_attempts={total_attempts}"
        )

    # ── All candidates exhausted ──────────────────────────────────────────────
    # error_type is "quota_exceeded" only when every failure was a quota/rate-limit error
    quota_only = bool(failure_types) and all(t == "quota" for t in failure_types)
    error_type = "quota_exceeded" if quota_only else "unavailable"

    logger.error(
        f"[AI] ALL models exhausted — giving up.  "
        f"error_type={error_type}  "
        f"total_attempts={total_attempts}  "
        f"models_tried={candidates}  "
        f"failure_types={failure_types}  "
        f"last_error={type(last_error).__name__}: {last_error}"
    )
    raise AIServiceUnavailableError(
        f"AI service exhausted after {total_attempts} attempt(s) "
        f"across {len(candidates)} model(s). "
        f"Last error: {last_error}",
        error_type=error_type,
    ) from last_error


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_success(primary: str, used: str, attempts: int) -> None:
    if used != primary:
        logger.info(
            f"[AI] SUCCESS via fallback — "
            f"primary={primary}  active_model={used}  total_attempts={attempts}"
        )
    elif attempts > 1:
        logger.info(
            f"[AI] SUCCESS after {attempts} attempt(s) — model={used}"
        )
    else:
        logger.info(f"[AI] SUCCESS — model={used}  attempts={attempts}")
