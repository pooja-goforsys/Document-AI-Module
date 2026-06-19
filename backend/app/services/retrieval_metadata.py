"""Shared metadata helpers for indexing and retrieval."""
from __future__ import annotations

from typing import Iterable


_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Travel": (
        "travel", "trip", "flight", "airfare", "hotel", "lodging",
        "accommodation", "mileage", "rental car", "taxi", "rideshare",
        "per diem", "meal allowance",
    ),
    "Expense": (
        "expense", "expenses", "reimbursement", "reimburse", "claim",
        "receipt", "invoice", "spend", "submission", "approval",
    ),
    "Leave": (
        "pto", "paid time off", "vacation", "leave", "sick", "holiday",
        "absence", "annual leave", "carry forward", "rollover",
    ),
    "Benefits": (
        "benefit", "benefits", "insurance", "health plan", "wellness",
        "retirement", "401k", "allowance",
    ),
    "Security": (
        "security", "incident", "breach", "vpn", "password", "mfa",
        "authentication", "access control",
    ),
}

_QUERY_CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "Travel": _CATEGORY_KEYWORDS["Travel"],
    "Expense": (
        "expense", "expenses", "reimbursement", "reimburse", "claim",
        "receipt", "invoice", "per diem", "mileage",
    ),
    "Leave": _CATEGORY_KEYWORDS["Leave"],
    "Benefits": _CATEGORY_KEYWORDS["Benefits"],
    "Security": _CATEGORY_KEYWORDS["Security"],
}


def infer_chunk_category(
    section: str | None,
    content: str | None,
    document_name: str | None = None,
) -> str | None:
    """Infer a coarse retrieval category from section/content metadata."""
    haystack = " ".join(
        part for part in (section, document_name, content[:500] if content else "") if part
    ).lower()
    if not haystack:
        return None

    scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score:
            scores[category] = score

    if not scores:
        return None

    return max(scores.items(), key=lambda item: item[1])[0]


def infer_query_categories(question: str | None) -> set[str]:
    """Return metadata categories that should be preferred for a query."""
    q = (question or "").lower()
    if not q:
        return set()

    categories = {
        category
        for category, keywords in _QUERY_CATEGORY_HINTS.items()
        if any(keyword in q for keyword in keywords)
    }

    # Travel workflows usually live across travel and expense policy sections.
    if "Travel" in categories:
        categories.add("Expense")

    return categories


def row_matches_categories(row: tuple, allowed_categories: Iterable[str]) -> bool:
    """Return True when a retrieval row matches any allowed metadata category."""
    allowed = set(allowed_categories)
    if not allowed:
        return True

    chunk = row[0]
    doc = row[1] if len(row) > 1 else None

    category = getattr(chunk, "category", None)
    if category:
        return category in allowed

    inferred = infer_chunk_category(
        getattr(chunk, "section_heading", None),
        getattr(chunk, "content", None),
        getattr(doc, "original_name", None),
    )
    return inferred in allowed if inferred else False

