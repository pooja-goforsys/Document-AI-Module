"""
Regression tests for `_retrieval_confidence_gate`.

Bug captured here: a previous edit accidentally nested
`_fetch_scope_chunks_by_order` inside the gate function, making the gate
fall through and return None. That caused every chat query to crash with:

    TypeError: cannot unpack non-iterable NoneType object

These tests pin down the contract so that regression cannot recur silently.
"""
import inspect

# Ensure SQLAlchemy mappers can compile before importing chat_service.
import app.models.notification    # noqa: F401
import app.models.auth            # noqa: F401
import app.models.saved_prompt    # noqa: F401
import app.models.analytics       # noqa: F401

from app.services.chat_service import (
    _retrieval_confidence_gate,
    _fetch_scope_chunks_by_order,
)


class _FakeChunk:
    pass


class _FakeDoc:
    pass


def _row(distance: float) -> tuple:
    """Build a fake (chunk, doc, distance) row in the retriever's shape."""
    return (_FakeChunk(), _FakeDoc(), distance)


# ── Contract: gate must always return a (bool, str, dict) tuple ──────────────


def test_gate_returns_three_tuple_for_non_empty_rows():
    rows = [_row(0.0017), _row(0.5774)]   # sims 0.9983 / 0.4226 — production case
    result = _retrieval_confidence_gate(rows, confidence_score=79.2)
    assert isinstance(result, tuple), f"expected tuple, got {type(result).__name__}"
    assert len(result) == 3
    block, reason, scores = result
    assert isinstance(block, bool)
    assert isinstance(reason, str)
    assert isinstance(scores, dict)


def test_gate_does_not_block_on_good_scores():
    rows = [_row(0.0017), _row(0.5774)]
    block, reason, scores = _retrieval_confidence_gate(rows, confidence_score=79.2)
    assert block is False, f"expected pass-through; got block=True reason={reason!r}"
    assert "best_sim" in scores


def test_gate_returns_early_on_empty_rows():
    assert _retrieval_confidence_gate([], 0.0) == (False, "", {})


def test_gate_blocks_low_composite_g2():
    # Very low similarities + very low composite → G2 should fire.
    rows = [_row(0.95), _row(0.99)]
    block, reason, _ = _retrieval_confidence_gate(rows, confidence_score=10.0)
    assert block is True
    assert reason.startswith("G")   # one of G0/G1/G2/G3 reasons


# ── Structural pin: helper must be defined at module level, not nested ───────


def test_fetch_helper_is_module_level_coroutine():
    assert inspect.iscoroutinefunction(_fetch_scope_chunks_by_order)
    assert _fetch_scope_chunks_by_order.__qualname__ == "_fetch_scope_chunks_by_order", (
        "If qualname is dotted, the helper was nested again inside another "
        "function — that's the bug this test was written to prevent."
    )
