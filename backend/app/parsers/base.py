import re
import logging
from dataclasses import dataclass
from abc import ABC, abstractmethod
from app.core.config import settings
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)


@dataclass
class ParsedChunk:
    text: str
    page_number: int
    chunk_index: int
    section_heading: str = ""
    metadata: dict | None = None


# ── Section heading detection ─────────────────────────────────────────────────
# Matches lines that are:
#   • Known section markers: PART I, ITEM 2, NOTE 3, EXHIBIT A, Chapter 5 ...
#   • ALL-CAPS headings 4-60 chars, ≤10 words, no financial data tokens ($, %)
#   • Title Case headings ending in policy/guideline/rule/procedure keywords
#   • Numbered headings: "1.", "5.1", "1.2.3" followed by a capitalised title
_SECTION_MARKERS = re.compile(
    r'^(?:PART|ITEM|SECTION|NOTES?|EXHIBIT|SCHEDULE|APPENDIX|CHAPTER)\s+\w',
    re.IGNORECASE,
)
_CAPS_HEADING = re.compile(r'^[A-Z][A-Z0-9\s\-&,\.\/\(\)\']{3,59}$')

# Title Case headings: starts with capital, contains a policy/chapter keyword,
# ≤12 words, no sentence-ending punctuation mid-line.
_TITLE_HEADING = re.compile(
    r'^[A-Z][a-zA-Z0-9][a-zA-Z0-9\s\-&,\.\/\(\)\']{2,78}'
    r'(?:Policy|Policies|Guidelines?|Rules?|Procedure|Procedures|'
    r'Requirements?|Standards?|Framework|Chapter|Section|Overview|'
    r'Introduction|Summary|Agreement|Contract|Addendum|Schedule)$'
)

# Numbered headings: "1.", "5.1", "1.2.3)" followed by capitalised text
_NUMBERED_HEADING = re.compile(
    r'^\d+(?:\.\d+)*[\.\)]\s+[A-Z][a-zA-Z\s\-&,\/]{3,59}$'
)

# Lines that contain financial data — these are NOT headings even if ALL-CAPS
_DATA_TOKENS = re.compile(r'[\$%]|\d{4,}|\|')


def _is_section_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) < 4 or len(stripped.split()) > 12:
        return False
    if _DATA_TOKENS.search(stripped):
        return False
    return (
        bool(_SECTION_MARKERS.match(stripped))
        or bool(_CAPS_HEADING.match(stripped))
        or bool(_TITLE_HEADING.match(stripped))
        or bool(_NUMBERED_HEADING.match(stripped))
    )


# ── Table line detection ──────────────────────────────────────────────────────
# A "table line" is a line that appears to contain structured numerical data:
#   • Pipe separators  |
#   • Dollar amounts   $1,234
#   • Large numbers    1,234  (4+ digits with comma)
#   • Whitespace-aligned columns ending in numbers
#   • Divider rows     ---  ===
_TABLE_RE = re.compile(
    r'\|'
    r'|\$\s*[\d,]+'
    r'|\b\d{1,3}(?:,\d{3})+\b'   # comma-formatted numbers e.g. 1,234,567
    r'|\t.{2,}\t'
    r'|^\s{2,}\S.*\s{3,}[\d,\-\(\)]+\s*$'
)
_DIVIDER_RE = re.compile(r'^[\-=_]{3,}\s*$')
_TABLE_BLOCK_START = "[[TABLE_START]]"
_TABLE_BLOCK_END = "[[TABLE_END]]"
_POLICY_UPDATE_RE = re.compile(
    r'\b(?:policy\s+update|changed|updated|old\s*:|new\s*:|limit\s+changed|effective\s+date)\b',
    re.IGNORECASE,
)


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped in {_TABLE_BLOCK_START, _TABLE_BLOCK_END}
        or bool(_TABLE_RE.search(line))
        or bool(_DIVIDER_RE.match(stripped))
    )


def _is_policy_update_line(line: str) -> bool:
    return bool(_POLICY_UPDATE_RE.search(line or ""))


# ── Table → structured text ───────────────────────────────────────────────────
# Converts markdown pipe tables to "Header: value" sentences so the embedding
# model captures the relationship between column headers and cell values.
# Before: "Enterprise | Unlimited | 500,000"
# After:  "Plan: Enterprise | Storage: Unlimited | API Calls: 500,000"
_PIPE_SEP_RE = re.compile(r'^[\|\-\+\s=]+$')


def _table_to_structured_text(table_text: str) -> str:
    """Convert a markdown pipe table to key:value structured text.

    Preserves the original if it is not a proper pipe table (e.g. raw
    financial data rows without headers).
    """
    lines = [ln.strip() for ln in table_text.splitlines() if ln.strip()]
    if not lines:
        return table_text

    # Identify header row (first non-separator line) and data rows
    header: list[str] | None = None
    data_rows: list[list[str]] = []
    for line in lines:
        if _PIPE_SEP_RE.match(line):
            continue  # separator row (---|---|---)
        cells = [c.strip() for c in line.split('|')]
        cells = [c for c in cells if c]  # drop empty edge cells
        if not cells:
            continue
        if header is None:
            header = cells
        else:
            data_rows.append(cells)

    # Need at least 1 header column and 1 data row to convert
    if not header or not data_rows:
        return table_text

    structured: list[str] = []
    for row in data_rows:
        pairs: list[str] = []
        for i, cell in enumerate(row):
            if i < len(header):
                pairs.append(f"{header[i]}: {cell}")
            else:
                pairs.append(cell)
        structured.append(", ".join(pairs))

    converted = "\n".join(structured)
    logger.debug(
        f"[Parser] Table→structured: {len(data_rows)} row(s) × {len(header)} col(s)"
    )
    return converted


# ── Token-aware splitter factory ─────────────────────────────────────────────

def _make_token_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    """Build a RecursiveCharacterTextSplitter that measures length in tokens.

    Uses tiktoken cl100k_base (GPT-4 / text-embedding-3 family encoding) for
    accurate token counting. Falls back to a character-based approximation
    (1 token ≈ 4 chars) if tiktoken is not installed.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=lambda text: len(enc.encode(text)),
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        logger.debug(
            f"[Parser] Token splitter ready — "
            f"encoder=cl100k_base  chunk={chunk_size}tok  overlap={chunk_overlap}tok"
        )
        return splitter
    except Exception as _e:
        logger.warning(
            f"[Parser] tiktoken unavailable ({type(_e).__name__}: {_e}) — "
            "falling back to character-based chunking. "
            f"Using approx char sizes: chunk={chunk_size * 4}  overlap={chunk_overlap * 4}"
        )
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size * 4,
            chunk_overlap=chunk_overlap * 4,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )


# ── Smart text splitter ───────────────────────────────────────────────────────

def _smart_split(
    text: str,
    max_size: int,
    overlap: int,
    fallback: RecursiveCharacterTextSplitter,
) -> list[tuple[str, str]]:
    """
    Split text into (chunk_text, section_heading) pairs.

    Rules:
    • Section headings reset the active heading and are NOT included as standalone
      chunks — they are prepended to the text/table that follows them.
    • Table blocks (contiguous runs of table-like lines) are kept as a single
      chunk unless they exceed max_size * 3, in which case they are split at
      blank-line boundaries.
    • Regular text is split by the LangChain RecursiveCharacterTextSplitter.
    """
    lines = text.splitlines()

    # ── Tag each line ─────────────────────────────────────────────────────────
    tagged: list[tuple[str, str]] = []   # (tag, line)
    for line in lines:
        if _is_section_heading(line):
            tagged.append(('heading', line))
        elif _is_table_line(line):
            tagged.append(('table', line))
        elif _is_policy_update_line(line):
            tagged.append(('policy_update', line))
        else:
            tagged.append(('text', line))

    # ── Group into segments ───────────────────────────────────────────────────
    segments: list[tuple[str, list[str]]] = []   # (tag, lines)
    cur_tag: str | None = None
    cur_lines: list[str] = []

    for tag, line in tagged:
        if tag == 'heading':
            if cur_lines:
                segments.append((cur_tag or 'text', cur_lines))
                cur_lines = []
            segments.append(('heading', [line]))
            cur_tag = None
        elif tag != cur_tag:
            if cur_lines:
                segments.append((cur_tag or 'text', cur_lines))
            cur_tag = tag
            cur_lines = [line]
        else:
            cur_lines.append(line)

    if cur_lines:
        segments.append((cur_tag or 'text', cur_lines))

    # ── Produce (chunk_text, heading) pairs ───────────────────────────────────
    current_heading = ""
    result: list[tuple[str, str]] = []

    for tag, seg_lines in segments:
        seg_text = '\n'.join(seg_lines).strip()
        if not seg_text:
            continue

        if tag == 'heading':
            current_heading = seg_text
            continue

        if tag == 'table':
            # Convert pipe tables to structured "Header: value" text so the
            # embedding model captures column-label relationships.
            structured = _table_to_structured_text(
                seg_text.replace(_TABLE_BLOCK_START, "").replace(_TABLE_BLOCK_END, "").strip()
            )
            # Keep intact unless very large; then split at blank lines
            if len(structured) <= max_size * 3:
                result.append((structured, current_heading))
            else:
                for part in re.split(r'\n{2,}', structured):
                    if part.strip():
                        result.append((part.strip(), current_heading))
        elif tag == 'policy_update':
            if len(seg_text) <= max_size * 3:
                result.append((seg_text, current_heading))
            else:
                for part in fallback.split_text(seg_text):
                    if part.strip():
                        result.append((part.strip(), current_heading))
        else:
            # Regular text — fall back to LangChain splitter
            for part in fallback.split_text(seg_text):
                if part.strip():
                    result.append((part.strip(), current_heading))

    return result


# ── Base parser ───────────────────────────────────────────────────────────────

class BaseParser(ABC):
    def __init__(self):
        self._char_splitter = _make_token_splitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )

    @abstractmethod
    def extract_chunks(self, file_path: str) -> list[ParsedChunk]:
        pass

    def _split_with_page(
        self,
        text: str,
        page_number: int,
        base_index: int,
        metadata: dict | None = None,
    ) -> list[ParsedChunk]:
        """
        Split a page's text into ParsedChunk objects.

        Section headings are injected as a [HEADING] prefix into the chunk text
        so the embedding captures the financial/document context of table data.

        Example:
          Heading:  "CONSOLIDATED STATEMENTS OF INCOME"
          Table:    "Revenue | 245,100 | 248,500"
          → stored: "[CONSOLIDATED STATEMENTS OF INCOME]\nRevenue | 245,100 | 248,500"
        """
        pairs = _smart_split(
            text,
            max_size=settings.CHUNK_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            fallback=self._char_splitter,
        )
        return [
            ParsedChunk(
                text=(f"[{heading}]\n{chunk_text}" if heading else chunk_text).strip(),
                page_number=page_number,
                chunk_index=base_index + i,
                section_heading=heading,
                metadata={**(metadata or {}), "page_number": page_number},
            )
            for i, (chunk_text, heading) in enumerate(pairs)
            if chunk_text.strip()
        ]
