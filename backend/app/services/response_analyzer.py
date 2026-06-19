"""
Post-generation response analysis.

After the main LLM response is streamed, this module inspects the generated
text and returns a structured metadata payload for the `metadata` SSE event:
  - response_type  : inferred UI presentation type
  - chart_data     : Recharts-compatible dataset (extracted from markdown tables)
  - mermaid_diagrams: list of mermaid diagram code found in the response
  - timeline_events : list of date/event pairs parsed from the response
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Response type detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_response_type(question: str, response_text: str) -> str:
    """Infer the best UI presentation type from the question and AI response."""
    q = question.lower()

    # Content-driven (response wins over question intent)
    if "```mermaid" in response_text:
        return "diagram"

    has_table = bool(re.search(r"\|[-:]+\|", response_text))
    if has_table:
        has_numeric = bool(re.search(r"\|\s*[\d.,]+%?\s*\|", response_text))
        if has_numeric:
            return "chart"
        if any(w in q for w in ("compare", "versus", " vs ", "vs.", "difference")):
            return "comparison"
        return "table"

    if re.search(r"```\w+", response_text):
        return "code"

    # Question-driven fallback
    if any(w in q for w in ("compare", "versus", " vs ", "vs.", "difference between", "which is better")):
        return "comparison"

    if any(w in q for w in ("chart", "graph", "plot", "statistics", "distribution")):
        return "chart"

    if any(w in q for w in ("diagram", "flowchart", "architecture", "workflow", "process flow", "sequence")):
        return "diagram"

    if any(w in q for w in ("timeline", "history of", "chronolog", "when did", "dates of")):
        return "timeline"

    if any(w in q for w in ("formula", "equation", "math", "calculate", "theorem", "proof")):
        return "formula"

    if any(w in q for w in ("summarize", "summary", "overview", "key points", "key takeaways", "tldr", "tl;dr")):
        return "summary"

    return "text"


# ─────────────────────────────────────────────────────────────────────────────
# Mermaid extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_mermaid_diagrams(response_text: str) -> list[str]:
    """Return all mermaid code-fence contents found in the response."""
    return [
        m.strip()
        for m in re.findall(r"```mermaid\n(.*?)```", response_text, re.DOTALL)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Chart data extraction from markdown tables
# ─────────────────────────────────────────────────────────────────────────────

def _parse_markdown_table(text: str) -> Optional[tuple[list[str], list[list[str]]]]:
    """
    Extract the first well-formed markdown table from text.
    Returns (headers, data_rows) or None.
    """
    lines = text.split("\n")
    table_lines: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if "|" in stripped:
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            if stripped:
                break  # Non-pipe, non-empty line ends the table

    if len(table_lines) < 3:
        return None

    # Validate separator (row index 1 must be |---|---|)
    sep_cells = [c.strip() for c in table_lines[1].split("|") if c.strip()]
    if not sep_cells or not all(re.match(r"[-:]+$", c) for c in sep_cells):
        return None

    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]
    rows = []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if cells:
            rows.append(cells)

    return (headers, rows) if rows else None


def extract_chart_data(response_text: str) -> Optional[dict]:
    """
    Build a Recharts-compatible dataset from the first markdown table in the
    response that contains at least one numeric column.
    """
    parsed = _parse_markdown_table(response_text)
    if not parsed:
        return None

    headers, rows = parsed
    if len(headers) < 2 or not rows:
        return None

    # Find columns with mostly-numeric values
    numeric_cols: list[int] = []
    for col_idx in range(1, len(headers)):
        hits = 0
        for row in rows:
            if col_idx < len(row):
                val_str = re.sub(r"[^0-9.\-]", "", row[col_idx])
                if val_str:
                    try:
                        float(val_str)
                        hits += 1
                    except ValueError:
                        pass
        if hits >= max(1, len(rows) // 2):
            numeric_cols.append(col_idx)

    if not numeric_cols:
        return None

    data: list[dict] = []
    for row in rows:
        point: dict = {"name": row[0] if row else ""}
        for col_idx in numeric_cols:
            if col_idx < len(row):
                val_str = re.sub(r"[^0-9.\-]", "", row[col_idx])
                try:
                    point[headers[col_idx]] = float(val_str)
                except (ValueError, IndexError):
                    point[headers[col_idx]] = 0.0
        data.append(point)

    series = [headers[i] for i in numeric_cols]
    return {
        "type": "bar",
        "title": f"{headers[0]} — {', '.join(series)}",
        "x_label": headers[0],
        "series": series,
        "data": data,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Timeline extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_timeline_events(response_text: str) -> Optional[list[dict]]:
    """
    Parse year/date → event patterns.
    Handles: "2021 → Launched", "2022 — Phase 1", "- **2023**: Milestone"
    """
    pattern = re.compile(
        r"(?:^|\n)\s*[-*•]?\s*\*{0,2}(\d{4}(?:[\/\-]\d{1,2})?)\*{0,2}"
        r"\s*(?:→|—|-|:|→)\s*\*{0,2}(.+?)\*{0,2}\s*(?=\n|$)",
        re.MULTILINE,
    )
    matches = pattern.findall(response_text)
    if len(matches) < 2:
        return None

    return [{"date": m[0].strip(), "event": m[1].strip()} for m in matches[:12]]


# ─────────────────────────────────────────────────────────────────────────────
# Answer type detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_answer_type(response_text: str) -> str:
    """Classify answer length from the generated response text."""
    word_count = len(response_text.split())
    if word_count < 60:
        return "short"
    if word_count < 250:
        return "medium"
    if word_count < 700:
        return "detailed"
    return "comprehensive"


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def analyze_response(question: str, response_text: str) -> dict:
    """
    Analyse the completed AI response and return a metadata payload.
    This is called once after streaming completes; errors are non-fatal.
    """
    response_type = detect_response_type(question, response_text)
    payload: dict = {"response_type": response_type, "answer_type": detect_answer_type(response_text)}

    try:
        diagrams = extract_mermaid_diagrams(response_text)
        if diagrams:
            payload["mermaid_diagrams"] = diagrams
    except Exception as exc:
        logger.warning(f"[Analyzer] mermaid extraction failed: {exc}")

    try:
        if response_type in ("chart", "table", "comparison"):
            chart = extract_chart_data(response_text)
            if chart:
                payload["chart_data"] = chart
    except Exception as exc:
        logger.warning(f"[Analyzer] chart extraction failed: {exc}")

    try:
        if response_type == "timeline":
            events = extract_timeline_events(response_text)
            if events:
                payload["timeline_events"] = events
    except Exception as exc:
        logger.warning(f"[Analyzer] timeline extraction failed: {exc}")

    return payload
