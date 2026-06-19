"""
Core RAG chat service — Enterprise Edition.

Pipeline:
  1. Embed user question (HuggingFace by default)
  2. Hybrid search: cosine-distance vector search + PostgreSQL FTS keyword search
  3. Build numbered context block from top-K results
  4. Send system prompt + conversation history + context + question to AI provider
  5. Stream tokens back to the frontend via SSE
  6. Persist session, messages, response_mode, and source citations to PostgreSQL

Enterprise additions:
  - Response modes (auto/simple/detailed/technical/summary/bullets/executive)
  - Multi-turn conversation history
  - Hybrid search with keyword boost
  - Dynamic top-K based on question complexity and similarity
  - Status SSE events (thinking/searching/generating)
  - Session pin/rename
  - Message feedback (like/dislike)
  - Response regeneration
"""
import uuid
import asyncio
import json
import math
import logging
from typing import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, delete

import time as _time

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.analytics import QueryAnalytics
from app.models.chat import ChatSession, ChatMessage, MessageFeedback, MessageRole
from app.schemas.chat import (
    ChatQueryRequest,
    ChatSessionResponse,
    ChatMessageResponse,
    FeedbackResponse,
    SourceCitation,
    RecentQueryResponse,
)
from app.embedders import get_embedder
from app.ai_providers import (
    get_ai_provider,
    get_provider_health,
    mark_provider_failed,
    mark_provider_healthy,
    get_fallback_provider,
    get_fallback_provider_name,
    get_ordered_provider_chain,
    record_llm_success,
    record_llm_failure,
)
from app.ai_providers.retry_utils import AIServiceUnavailableError
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core import pgvector_search as _pv
from app.services.response_analyzer import analyze_response
from app.services.retrieval_metadata import infer_query_categories, row_matches_categories

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Response mode instructions
# These are appended after the scope header and before the base SYSTEM_PROMPT
# so they specialize the output style without weakening the grounding rules.
# ─────────────────────────────────────────────────────────────────────────────
MODE_INSTRUCTIONS: dict[str, str] = {
    "auto": "",  # no extra instruction — let the model detect question type
    "simple": (
        "RESPONSE MODE — SIMPLE\n"
        "Provide a concise, direct answer in 2–4 sentences maximum. "
        "No headers. No bullet lists. Plain prose with inline citations only. "
        "Ideal for yes/no questions, single-fact lookups, and short definitions.\n\n"
    ),
    "detailed": (
        "RESPONSE MODE — DETAILED\n"
        "Provide a thorough, well-structured answer using all relevant context. "
        "Use Markdown headers (##) to organize sections. "
        "Include explanations, examples from the documents, and a summary. "
        "Cite every claim with [N]. Aim for comprehensive coverage.\n\n"
    ),
    "technical": (
        "RESPONSE MODE — TECHNICAL\n"
        "Provide a technically precise answer targeting an expert audience. "
        "Use exact terminology from the documents. Include code blocks with language "
        "identifiers where applicable. Show data types, interfaces, algorithms, or "
        "configurations verbatim from context. Omit introductory explanations. "
        "Cite every claim with [N].\n\n"
    ),
    "summary": (
        "RESPONSE MODE — SUMMARY\n"
        "Provide a high-level summary of the most important information related to "
        "the question. 3–5 bullet points covering key facts only. "
        "Each bullet must end with [N]. No elaboration beyond what context states.\n\n"
    ),
    "bullets": (
        "RESPONSE MODE — BULLETS\n"
        "Answer entirely in bullet-point format. "
        "Each bullet is one concrete fact or step from context, ending with [N]. "
        "Group related bullets under bold headers if there are more than 5 points. "
        "Do not write prose paragraphs.\n\n"
    ),
    "executive": (
        "RESPONSE MODE — EXECUTIVE SUMMARY\n"
        "Structure the response as an executive briefing:\n"
        "**TL;DR** — one sentence conclusion [N].\n"
        "**Key Points** — 3–5 bullets of the most business-relevant facts [N].\n"
        "**Detail** — 1 short paragraph for context [N].\n"
        "Use plain language. Minimize jargon. Focus on implications and decisions.\n\n"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# Sent as the AI provider's "system instruction" so it is always in effect and
# cannot be overridden by the user's question.
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are an enterprise-grade Document AI Assistant.

Your primary responsibility is to answer questions ONLY from the uploaded documents.

========================
UNIVERSAL ANSWER PROTOCOL
========================

These rules apply to every question, regardless of which response format the
intent classifier selects below. They override any conflicting format detail.

A. RETRIEVE BROADLY. Use every relevant excerpt across pages and documents.
   Combine information from multiple sections when the question requires it.

B. REASON, DO NOT QUOTE. Never return raw chunks. Synthesize a clear answer
   from the evidence — perform compliance checks, calculations, date math,
   timeline analysis, comparisons, and policy interpretation as needed.

C. EVALUATE ALL APPLICABLE RULES. When multiple policies, rules, or sections
   apply, evaluate each before producing the answer. For compliance scenarios,
   identify ALL violations AND all compliant items, and explain each.

D. DATE QUESTIONS. Compute exact day/month/year deltas when both dates are
   in the documents. Show the calculation.

E. NUMERICAL QUESTIONS. Perform the arithmetic using only retrieved values;
   show the operands and the result. Never estimate.

F. INFERENCE LABEL. If the answer requires inference (ordering of risks,
   prioritization, combining facts to reach a conclusion not literally stated),
   append exactly this sentence after the conclusion:
       "This conclusion is based on the information available in the documents."

G. MISSING INFORMATION. If the documents do not contain enough information,
   state exactly what is missing (which fact, policy section, value, date).
   Never invent. Never fall back to general knowledge.

H. CONFLICTING SOURCES. If two excerpts contradict, list both sources with
   their citations and explain the conflict — do not silently choose one.

I. ALWAYS CITE. Every factual claim carries an inline [N] citation. The
   Sources section must list document name, section heading (when known),
   and page number for each [N].

J. ALWAYS REPORT CONFIDENCE. End every non-trivial answer with a Confidence
   line: High (direct match), Medium (synthesis), Low (partial / inference).

========================
CORE RULES
========================

1. NEVER hallucinate.
2. NEVER invent facts.
3. NEVER guess.
4. Every answer must be supported by retrieved document evidence.
5. Always cite source file name and page number.
6. If evidence is insufficient, explicitly state that the answer was not found.
7. Prefer exact answers over summaries whenever possible.

========================
EXPLICIT ANSWER PRIORITY
========================

If a retrieved excerpt contains the exact answer to the question:
  → Answer directly. Do NOT return "Insufficient information."
  → Do NOT say "the document doesn't specify" if the value appears in ANY chunk.

Before declining to answer, verify ALL of the following:
  ✓ The answer is absent from every retrieved chunk.
  ✓ The answer cannot be derived from retrieved facts.
Only decline after both checks confirm no answer exists.

Example failure to avoid:
  Question: "What is the API limit for NexaCloud Professional?"
  Retrieved: "Plan: Professional | API Limit: 50,000 requests/day"
  WRONG: "The document does not specify the API limit."
  CORRECT: "50,000 requests/day [N]"

========================
EVIDENCE MATCHING RULES
========================

Only use retrieved content that DIRECTLY matches the question topic.

Priority order:
  1. Exact topic match (same product/policy/term name)
  2. Same policy section
  3. Supporting context from adjacent chunks

If a retrieved chunk belongs to a different product, policy, time period,
or unrelated section — IGNORE it even if it ranks highly.
Do NOT let irrelevant chunks dilute or contradict the correct answer.

========================
RETRIEVAL STRATEGY
========================

Before answering:

Step 1 — Classify the question:

  Category A — FACT RETRIEVAL
    Who is the CEO? | What is revenue? | When was the company founded?
    What is Azure AI Foundry?

  Category B — NUMERIC RETRIEVAL
    Revenue | Net income | EPS | Cash flow | Assets | Liabilities

  Category C — COMPARISON
    Compare FY2024 vs FY2025 | Compare Product A and Product B
    Compare Revenue and Net Income

  Category D — SUMMARY
    Summarize management outlook | Summarize AI strategy | Executive summary

  Category E — ANALYSIS
    Why did revenue increase? | How does AI contribute to growth?
    What are the competitive advantages?

  Category F — MULTI-HOP ARITHMETIC
    Total PTO | Combined leave | Grand total | How much altogether?

  Category G — POLICY REASONING
    Is approval required? | Does this employee qualify? | What is the limit for X?
    Any question requiring threshold check, eligibility rule, or policy application.

  Category H — RANKING
    Which plan has the highest limit? | Rank products by price | Top 3 by revenue?
    Any question asking for ordering, best/worst, highest/lowest across multiple items.

  Category I — CROSS-DOCUMENT REASONING
    Any question that requires combining facts from more than one uploaded document.

Step 2 — Expand the query mentally with synonyms before matching:
  "approval needed" → approval threshold, authorization, expense approval
  "API limit"       → request limit, daily requests, usage cap
  "backup frequency" → backup schedule, backup interval, backup every

Step 3 — Apply the rules for that category (see sections below).

========================
FACT RETRIEVAL RULES (Category A)
========================

For entity/role questions (CEO, Chairman, President, Founder, CFO, COO,
Director, Vice President, etc.):

STEP 1: Identify the exact role from the question.

STEP 2: Scan ALL retrieved excerpts for text that EXPLICITLY assigns that
role to a named person. Require the name and the role title to appear together
in the same sentence or adjacent text.
Ignore names that appear nearby for unrelated reasons (board lists, authors,
references, quoted persons).

STEP 3: If exactly one name is role-matched → answer directly. Do NOT mention
other names found in the same chunks.

STEP 4: Combine evidence across excerpts freely.
Name in [1] + title in [2] = one complete answer.

Output format:

Answer:
[Full Name] is the [Role Title]. [N]

Source:
[Document Name]

Page:
[page number]

Confidence:
High | Medium | Low

Example:
  Answer:
  Satya Nadella is the Chairman and Chief Executive Officer. [1]

  Source:
  2025_AnnualReport.pdf

  Page:
  5

  Confidence:
  High

========================
NUMERIC RETRIEVAL RULES (Category B)
========================

For financial metrics:

  Revenue | Net Income | Operating Income | EPS | Cash Flow |
  Assets | Liabilities | Debt | R&D Expense

Search in this order:
  1. Financial Highlights
  2. Income Statement
  3. Balance Sheet
  4. Cash Flow Statement
  5. MD&A
  6. Key Metrics

Validation rules:
  • If the retrieved chunk does NOT contain the requested metric name → discard
    and retrieve again.
  • Never substitute one metric for another:
    EPS ≠ Dividend Per Share
    Revenue ≠ Remaining Performance Obligation
    Net Income ≠ Operating Income
  • Copy all numbers VERBATIM — never round, estimate, or paraphrase.
  • Always confirm the fiscal year label (FY2024, FY2025, "fiscal year ended…")
    in the same or adjacent excerpt. If absent, note it explicitly.

Output format:

**[Metric Name]:** [Exact Value] [N]
**Period:** [Fiscal Year / Quarter]
**Source:** [Document Name], Page [page number]
**Confidence:** High | Medium | Low

========================
MULTI-HOP ARITHMETIC (Category F)
========================

For questions whose answer requires COMBINING values from multiple excerpts:

  "Total PTO"     = base days [1] + wellness days [2] + sick days [3]
  "Combined cost" = plan fee [1] + setup fee [2]
  "Net benefit"   = gross allowance [1] − deductions [2]

Rules:
  STEP 1 — Scan ALL retrieved excerpts for every numeric component.
  STEP 2 — Identify the operation: sum, subtract, percentage, or average.
  STEP 3 — Show the calculation explicitly with citations on every value:
              24 days (base PTO) [1] + 3 days (wellness) [2] = 27 days
  STEP 4 — State the final answer in **bold**.
  STEP 5 — Never invent or estimate any component — every number must have [N].

Output format:

**Breakdown:**
- [Component label]: [value] [N]
- [Component label]: [value] [N]

**Total: [calculated result]**

**Sources:**
[N] [Document Name], Page [page number]

**Confidence:** High | Medium | Low

========================
COMPARISON RULES (Category C)
========================

Retrieve each entity independently, then compare.

Never return Not Found unless BOTH values cannot be located.

Output:

## Comparison: [Entity A] vs [Entity B]

| Metric | [Entity A] | [Entity B] | Change |
|--------|-----------|-----------|--------|
| [metric] [N] | [value] | [value] | ▲/▼ X% or N/A |

**Key Differences**
**Sources**
**Confidence**

========================
SUMMARY RULES (Category D)
========================

Retrieve at least 15–30 relevant chunks. Never answer from a single chunk.

Output:

**Executive Summary** [N]
**Key Points** [N]
**Financial Highlights** [N] (if available)
**Strategic Priorities** [N] (if available)
**Sources**

========================
ANALYSIS RULES (Category E)
========================

Retrieve multiple supporting chunks. Reason ONLY from retrieved evidence.
Do not invent reasoning.

Output:

**Answer:** [synthesized answer] [N]
**Reason:** [brief reasoning chain]
**Source:** [Document Name] | Page [page number] | [Section heading when known]

========================
POLICY REASONING (Category G)
========================

For questions involving thresholds, eligibility, calculations, or policy application:

STEP 1 — Extract every relevant fact from the retrieved chunks.
STEP 2 — Identify the policy rule or threshold that applies.
STEP 3 — Apply the rule to the scenario — show each step explicitly.
STEP 4 — State the final answer in bold.

Always perform reasoning BEFORE generating the answer.

Boundary condition rules:
  "more than 5 years" → 5 years = Does NOT qualify | 6 years = Qualifies
  "at least 30 days"  → 30 days = Qualifies        | 29 days = Does NOT qualify
  "up to $500"        → $500 = Allowed              | $501 = Exceeds limit
  "over $1,000"       → $1,000 = Does NOT trigger   | $1,001 = Triggers
  Evaluate the EXACT boundary every time — never assume inclusive/exclusive.

Output format:

**Facts:**
- [Fact from document] [N]
- [Fact from document] [N]

**Reasoning:**
[Show each step of the policy application or calculation]

**Answer:**
**[Final answer in bold]**

**Sources:**
[N] [Document Name], Page [page number]

**Confidence:** High | Medium | Low

========================
RANKING RULES (Category H)
========================

For questions asking which item is highest, lowest, best, worst, or requesting an
ordered list across multiple options:

STEP 1 — Extract the relevant metric and ALL candidate values from the retrieved
          chunks. Do not stop at the first value found.
STEP 2 — Assign each value to its named item (plan, product, year, person, etc.).
STEP 3 — Sort the values correctly (ascending or descending per the question).
STEP 4 — State the ranked result explicitly.
STEP 5 — If a value is missing for one candidate, list it as "N/A" — never omit it.

Output format:

**Ranked [Metric] ([highest first / lowest first]):**
1. [Item A]: [Value] [N]
2. [Item B]: [Value] [N]
3. [Item C]: [Value] [N]

**Answer:** [Item A] has the highest [Metric] at [Value]. [N]

**Sources:**
[N] [Document Name], Page [page number]

**Confidence:** High | Medium | Low

========================
CROSS-DOCUMENT REASONING (Category I)
========================

For questions that require combining evidence from more than one uploaded document:

STEP 1 — Identify which documents each piece of evidence comes from.
STEP 2 — Treat each document as a separate authority — do NOT assume they agree.
STEP 3 — Merge facts where they align. Flag contradictions using CONFLICT RESOLUTION.
STEP 4 — Always attribute every fact to its source document [N].
STEP 5 — State the final synthesized answer explicitly.

Rules:
• Never mix up which fact came from which document.
• If Document A and Document B give different values for the same fact, follow
  CONFLICT RESOLUTION — do NOT silently pick one.
• When documents complement each other (different facts about the same entity),
  combine them freely into one coherent answer.

Output format: use the standard Answer / Reason / Source / Confidence
structure (see DEFAULT RESPONSE FORMAT below).

========================
STRUCTURED DATA RULES
========================

When product plans, pricing tables, limits, or policy matrices appear:

1. Convert each row into named fields before reasoning:
   Row: "Enterprise | Unlimited | 500,000"
   → Plan: Enterprise | Storage: Unlimited | API Limit: 500,000

2. Match the question to the CORRECT row — verify the plan or tier name exactly.
3. Never mix values from different rows or plans.
4. Always state which row/plan/tier the answer comes from.

Example:
  Question: "What is the API limit for NexaCloud Professional?"
  Row: Plan: Professional | Storage: 5TB | API Limit: 50,000
  Answer: "The API limit for NexaCloud Professional is **50,000 requests/day** [N]"

========================
CONFLICT RESOLUTION
========================

When two retrieved chunks provide different values for the same question:

DO NOT silently choose one. DO NOT return "Conflicting information exists."

Instead, follow this process:

Step 1 — Attempt to resolve automatically:
  a. Prefer the official/authoritative section (leadership page, financial statement,
     dedicated definition section) over a passing reference.
  b. If values are from different fiscal years or policy versions, state both
     with their period labels — this is NOT a conflict, it is period data.
  c. Ignore chunks that mention the entity in an unrelated context.

Step 2 — If conflict cannot be resolved, report it explicitly:

  **Conflict Detected**

  **Source A:** [Value from source A] [N]
  → *[Document Name], Page [page]*

  **Source B:** [Value from source B] [N]
  → *[Document Name], Page [page]*

  **Recommendation:** The policy owner should verify which version is current.

========================
NOT FOUND RULES
========================

Return "Not Found" ONLY after ALL of the following:
  1. Full retrieval completed across all relevant chunks.
  2. All related sections searched (synonyms, adjacent topics).
  3. The answer is not present in ANY chunk.
  4. The answer cannot be derived from retrieved facts.

Do NOT infer missing values.
Do NOT fabricate calculations from absent data.
Do NOT return "Not Found" because the answer requires reasoning — reason first.

Format:

**Answer:**
The uploaded documents do not contain sufficient information to answer
this question.

**Searched:**
[List the document sections and topics that were checked]

**What was looked for:**
[State specifically what value/fact was searched for]

**Confidence:**
Very Low

========================
QUALITY CHECK BEFORE RESPONDING
========================

Verify ALL of the following before generating the final answer:

  ✓ Question answered directly — not deflected
  ✓ Explicit answer used if present in any chunk (not "Insufficient information")
  ✓ Correct metric used (never substituted)
  ✓ Correct person/title matched to the queried role
  ✓ Source file name attached
  ✓ Page number attached
  ✓ No hallucinations
  ✓ No irrelevant chunks included
  ✓ "Conflicting information exists" NOT used — resolve or report both values
  ✓ Boundary conditions evaluated exactly ("more than 5" → 5 fails, 6 passes)
  ✓ Table rows matched to the correct plan/tier name — no cross-row mixing
  ✓ Policy reasoning shown step-by-step before stating the final answer

========================
SOURCE REQUIREMENTS (MANDATORY)
========================

Every answer must include:

**Sources:**
[N] [Document Name], Page [page number]

If page number unavailable:
  Page: Not Available

Omitting citations is a critical failure.

========================
CONFIDENCE (MANDATORY)
========================

End every response with:
  **Confidence:** Very High | High | Medium | Low | Very Low

  Very High — the same answer appears in multiple independent sources
  High      — single authoritative source with direct supporting evidence
  Medium    — multiple sources with minor ambiguity or paraphrasing required
  Low       — partial or indirect evidence only
  Very Low  — no supporting evidence (use for Not Found responses)

Confidence selection rules:
  • Two sources agree on the exact value → Very High
  • One source states the value directly → High
  • Requires combining 2-4 chunks with minor interpretation → Medium
  • Only tangentially related evidence → Low
  • Answer absent from all chunks → Very Low

========================
DEFAULT RESPONSE FORMAT (override when TYPE directive is present)
========================

If a "RESPONSE FORMAT — TYPE N" directive appears at the top of this prompt,
use THAT format instead.

For all other responses, use this clean user-facing structure
(omit any section that does not apply — DO NOT include empty sections):

**Answer:**
[Direct synthesized conclusion with inline [N] citations on every factual claim.
 Lead with the answer; no preamble.]

**Reason:** (include ONLY for reasoning, compliance, comparison, calculation,
or date-arithmetic questions; OMIT entirely for direct single-fact lookups)
[One short paragraph: which rule, threshold, calculation, or evidence chain
 produced the answer. Keep it brief.]

**Source:**
[Document Name] | Page [page number] | [Section heading when known]
(Add one line per cited [N]. Combine duplicate sources.)

**Confidence:** High | Medium | Low

NEVER add: "Supporting Evidence" bullet list, "What was searched", "What was
looked for", retrieved chunk counts, relevance percentages, or any other
retrieval diagnostics. Those are backend-only.

========================
FALLBACK REASONING RULE
========================

If the AI generation layer is unavailable, STILL perform deterministic reasoning
from the retrieved facts:
  • For calculations — show formula and compute the result.
  • For comparisons — state which value is greater/smaller and why.
  • For rankings — extract all values, sort them, return the ordered list.
  • For eligibility checks — evaluate the policy condition against the given facts.
  • For policy decisions — apply every condition step by step.

Never return raw document excerpts as the final answer when reasoning is possible.

========================
FORMATTING
========================

- Markdown for all responses
- Tables require the |---|---| separator row
- Length proportional to question complexity
- Skip any section with no supporting context — never fabricate content

========================
FINAL RULE
========================

Accuracy is more important than completeness.
Never hallucinate.
Always prioritize evidence over assumptions.
"""

# Canonical refusal messages — keep in sync with SYSTEM_PROMPT wording above
NO_RELEVANT_MSG = (
    "The uploaded documents do not contain sufficient information to answer "
    "this question."
)
NO_CONFLICT_MSG = "Conflicting information exists in the retrieved documents."


def _is_page_aggregation_query(question: str) -> bool:
    """True when the user asks for all pages related to a topic."""
    q = question.lower().strip()
    page_phrase = any(
        phrase in q
        for phrase in (
            "which pages", "what pages", "all pages", "pages contain",
            "pages mention", "pages include", "page numbers", "list pages",
            "return pages",
        )
    )
    aggregate_phrase = any(
        phrase in q
        for phrase in (
            "contain", "contains", "mention", "mentions", "include", "includes",
            "related to", "about", "where", "all",
        )
    )
    return page_phrase and aggregate_phrase


def _intent_classify(question: str) -> str:
    """Classify question intent for response format selection and top-k tuning.

    Returns one of:
      oneword | shortfact | numerical | definition | explanation | summary |
      comparison | table | list | pageref | analytical | chart | financial |
      process | compliance | general
    """
    q     = question.lower().strip().rstrip('?.,!')
    words = [w.strip('?.,!;:\'"') for w in q.split() if w.strip('?.,!;:\'"')]
    n     = len(words)

    if _is_page_aggregation_query(question):
        return 'pageagg'

    # ── Page reference ─────────────────────────────────────────────────────────
    if any(p in q for p in ('which page', 'what page', 'on what page', 'where is ',
                             'where can i find', 'where does', 'which section',
                             'page number of', 'what chapter')):
        return 'pageref'

    # ── Chart / visualization ──────────────────────────────────────────────────
    if any(p in q for p in ('chart', 'graph', 'plot', 'visualize', 'visualization',
                             'bar chart', 'pie chart', 'trend graph', 'show trend',
                             'growth chart', 'line chart')):
        return 'chart'

    # ── Explicit table request ─────────────────────────────────────────────────
    if any(p in q for p in ('show table', 'in a table', 'list as table', 'tabulate',
                             'table of ', 'table showing', 'breakdown of',
                             'show breakdown', ' by year', ' by quarter',
                             ' by month', ' by department', ' by region',
                             'year-by-year', 'year by year')):
        return 'table'

    # ── Comparison / period-over-period ──────────────────────────────────────
    if any(p in q for p in (
        ' vs ', ' versus ', 'compare ', 'difference between',
        'differences between', 'contrast ', 'similarities between',
        'which is better', 'better than',
        # year-over-year / period comparison patterns
        'year over year', ' yoy', 'year-over-year', 'yoy growth',
        'compared to fy', 'compared to last year', 'compared to previous',
        'compared to 20', 'change from 20', 'growth from 20',
        'change between', 'from fy20', 'fy20', 'from fiscal',
        'across years', 'across periods', 'across documents',
        'period comparison', 'multi-year', 'multi year',
        'how did ', 'how has ', 'how have ',
        'growth in ', 'change in ', 'increase in ', 'decrease in ',
        'quarter over quarter', ' qoq', 'period over period',
        'compared with', 'relative to ',
    )):
        return 'comparison'

    # ── Multi-hop arithmetic ──────────────────────────────────────────────────
    # Questions whose answer requires summing or combining values from multiple
    # chunks — e.g. "total PTO = base days + wellness days + sick days".
    if any(p in q for p in (
        'total pto', 'total leave', 'total days', 'total vacation',
        'how many days total', 'days do i get', 'days per year',
        'total time off', 'days available', 'days can i take',
        'combined total', 'add up', 'in total', 'altogether',
        'sum of', 'total allowance', 'total benefit', 'total entitlement',
        'total coverage', 'total storage', 'combined capacity', 'total limit',
        'total amount', 'total cost', 'how much total', 'grand total',
        'days passed between', 'days between', 'how many days passed',
        'how many days elapsed', 'time between', 'reimbursement increase',
        'increase amount', 'increase percentage', 'percentage increase',
        'percent increase', 'calculate ',
    )):
        return 'arithmetic'

    # ── Ranking ───────────────────────────────────────────────────────────────
    if any(p in q for p in (
        'rank ', 'ranking ', 'ranked ', 'highest ', 'lowest ', 'most expensive',
        'least expensive', 'cheapest ', 'most popular', 'top 3', 'top 5', 'top ten',
        'best plan', 'worst plan', 'highest limit', 'lowest limit', 'largest ',
        'smallest ', 'order by ', 'sorted by ', 'in order of', 'from highest',
        'from lowest', 'which has the most', 'which has the least',
        'which is the highest', 'which is the lowest', 'which is the largest',
        'which is the smallest', 'which is the cheapest', 'which is the most',
        'best performing', 'worst performing',
    )):
        return 'ranking'

    # ── Summary ───────────────────────────────────────────────────────────────
    if any(p in q for p in ('summarize', 'summarise', 'summary', 'key points',
                             'main points', 'executive summary', 'brief overview',
                             'in a nutshell', 'tldr', 'tl;dr', 'key takeaways',
                             'top points', 'highlights of',
                             'overview of', 'give me a summary', 'give me an overview',
                             'what happened', 'describe the document', 'key findings',
                             )):
        return 'summary'

    # ── Analytical ────────────────────────────────────────────────────────────
    if any(p in q for p in ('what are the risks', 'what are the challenges',
                             'what are the issues', 'what are the problems',
                             'what are the implications', 'analyze ', 'analyse ',
                             'why did ', 'why does ', 'why is ', 'root cause',
                             'what caused', 'what factors', 'future opportunities',
                             'major risks', 'main risks', 'key risks',
                             'pros and cons', 'swot',
                             'what impact', 'how does this affect', 'strategic implications',
                             'business impact', 'trend analysis', 'what drives',
                             'what contributes', 'root causes', 'key drivers',
                             )):
        return 'analytical'

    # Compliance / policy interpretation.
    if any(p in q for p in (
        'would this be allowed', 'would this action be allowed',
        'would an employee', 'would someone', 'is this allowed',
        'is it allowed', 'is this compliant', 'be compliant',
        'would be compliant', 'is compliant', 'non-compliant',
        'violation', 'violations', 'violates', 'breach of policy',
        'conditions must be met', 'before this action can be approved',
        'can be approved', 'approval conditions', 'exceptions mentioned',
        'any exceptions', 'exception to this rule', 'eligible for',
        'qualify for', 'qualifies for',
    )):
        return 'compliance'

    # ── Numerical metric (bare noun ≤2 words, or explicit how-much/many + metric)
    _metric = {
        'revenue', 'revenues', 'profit', 'profits', 'loss', 'losses', 'income',
        'earnings', 'ebitda', 'eps', 'margin', 'sales', 'cost', 'costs',
        'expense', 'expenses', 'budget', 'funding', 'valuation', 'market cap',
        'net income', 'gross profit', 'operating income', 'cash flow',
        'assets', 'liabilities', 'salary', 'salaries', 'wage', 'wages',
        'headcount', 'employees',
    }
    if n <= 2 and any(w in _metric for w in words):
        return 'numerical'
    if (q.startswith('how much') or q.startswith('how many')) and any(w in _metric for w in words):
        return 'numerical'

    # ── Policy / procedure questions ─────────────────────────────────────────
    # Must precede the financial check: "expense policy", "travel policy",
    # "salary guideline" etc. contain financial keywords but should be answered
    # from policy documents, not financial statements.
    _POLICY_TERMS_LOCAL = frozenset({
        'policy', 'policies', 'guideline', 'guidelines', 'procedure', 'procedures',
        'rule', 'rules', 'regulation', 'regulations', 'standard', 'standards',
        'reimbursement', 'allowance', 'compliance', 'code', 'conduct',
        'handbook', 'manual', 'protocol',
    })
    if any(w in _POLICY_TERMS_LOCAL for w in words):
        return 'explanation'

    # ── Broader financial analysis ────────────────────────────────────────────
    if any(w in _metric for w in words):
        return 'financial'

    # ── List / enumeration ────────────────────────────────────────────────────
    if any(p in q for p in ('list all', 'list the', 'list of', 'list every',
                             'enumerate', 'what are all', 'what are the',
                             'types of ', 'advantages of', 'disadvantages of',
                             'features of ', 'benefits of ', 'examples of ',
                             'give me all', 'show all ', 'all the ')):
        return 'list'

    # ── Explanation / theory ──────────────────────────────────────────────────
    if any(p in q for p in ('explain ', 'how does ', 'how do ', 'how is ',
                             'how are ', 'describe ', 'elaborate ',
                             'walk me through', 'tell me about ',
                             'in detail', 'in-depth', 'step by step',
                             'step-by-step', 'in depth', 'comprehensive',
                             'everything about', 'all about ', 'how it works',
                             'how they work')):
        return 'explanation'

    # ── Person / role lookup ───────────────────────────────────────────────────
    # "who is the CEO?" / "who is the founder?" / bare "CEO?" → person intent
    _ROLE_TERMS_LOCAL = frozenset({
        'ceo', 'cfo', 'cto', 'coo', 'cso', 'cpo', 'cmo',
        'chairman', 'chair', 'president', 'founder', 'co-founder',
        'chief executive', 'chief financial', 'chief technology', 'chief operating',
        'managing director', 'executive director',
        'vp', 'vice president', 'head of',
    })
    if (
        any(q.startswith(s) for s in ('who is ', 'who are ', 'who was ', "who's "))
        or any(term in q for term in _ROLE_TERMS_LOCAL)
    ):
        return 'person'

    # ── Definition (concept/term) ──────────────────────────────────────────────
    if any(q.startswith(s) for s in ('what is ', 'what are ', 'define ',
                                      'definition of ', 'meaning of ',
                                      'what does ')) and n <= 10:
        return 'definition'

    # ── Process / how-to ──────────────────────────────────────────────────────
    if any(p in q for p in ('how to ', 'how do i ', 'steps to ',
                             'procedure for ', 'instructions for ',
                             'guide to ', 'process of ')):
        return 'process'

    # ── One-word bare noun (CEO?  Founded?  Language?) ────────────────────────
    if n == 1:
        return 'oneword'

    # ── Short single-fact lookup ──────────────────────────────────────────────
    if n <= 8 and any(q.startswith(s) for s in ('who ', 'when ', 'how many ',
                                                  'how much ', 'how long ',
                                                  'what year', 'what date',
                                                  'which year', 'which date',
                                                  'what number', 'what version',
                                                  'what percent')):
        return 'shortfact'
    if n <= 2:
        return 'shortfact'

    return 'general'


# Per-intent retrieval depth: narrow intents (fact, pageref) need 2–3 focused
# chunks; broad intents (summary, comparison) need 7–8 for full coverage.
_INTENT_TOP_K: dict[str, int] = {
    'oneword':     2,
    'shortfact':   3,
    'person':      3,
    'numerical':   3,
    'definition':  4,
    'explanation': 8,
    'summary':     18,   # broad coverage — summary must aggregate the whole document
    'comparison':  10,
    'table':       5,
    'list':        12,   # numbered lists may span many chunks; preserve full enumeration
    'pageref':     3,
    'pageagg':     20,
    'analytical':  7,
    'chart':       5,
    'financial':   5,
    'process':     6,
    'arithmetic':  8,  # needs all component chunks to construct the sum
    'ranking':     8,  # must see all candidates to rank them correctly
    'compliance':  15,  # multi-policy scenarios need wide recall — every distinct policy
                        # category in the scenario must contribute at least one chunk, so we
                        # over-fetch and let the cross-encoder + dedup prune.
    # 'general' falls back to settings.RERANKER_TOP_K
}


def _detect_question_complexity(question: str) -> str:
    """Return 'fact', 'definition', 'short', 'medium', or 'detailed'."""
    words = question.split()
    n = len(words)
    q = question.lower().strip().rstrip('?')

    # "fact" — single data-point lookup: name, number, date, yes/no
    fact_starters = (
        "who ", "when ", "how many ", "how much ", "how long ", "how often ",
        "what year", "what date", "what number", "what version", "what percent",
        "which year", "which date",
    )
    if n <= 8 and any(q.startswith(s) for s in fact_starters):
        return "fact"
    if n <= 3:
        return "fact"

    # "definition" — identify or define a term
    definition_patterns = (
        "what is ", "what are ", "define ", "definition of ", "meaning of ",
        "what does ", "what do ", "who is ", "who are ",
    )
    if any(q.startswith(p) for p in definition_patterns) and n <= 10:
        return "definition"

    if n <= 5:
        return "short"

    detail_signals = (
        "explain", "describe", "elaborate", "in detail", "in-depth", "in depth",
        "comprehensive", "overview", "how does", "how do i", "step by step",
        "step-by-step", "walk me through", "everything about", "all about",
        "what is the difference", "compare", "versus", " vs ", "thoroughly",
        "complete explanation", "tell me about", "what are all",
    )
    if any(s in q for s in detail_signals):
        return "detailed"

    return "medium" if n <= 15 else "detailed"


# ── Domain synonym map ────────────────────────────────────────────────────────
# Appended to the embed query so the bi-encoder captures all semantic variants.
# Also used to expand FTS keyword searches.
# Key: lowercase word as it appears in a question.
# Value: list of synonyms / alternate phrasings.
_QUERY_SYNONYMS: dict[str, list[str]] = {
    # Finance / Business
    "revenue":       ["sales", "income", "earnings", "turnover", "receipts"],
    "revenues":      ["sales", "income", "earnings", "turnover"],
    "profit":        ["net income", "earnings", "net profit", "gain", "surplus"],
    "profits":       ["net income", "earnings", "surplus", "gain"],
    "cost":          ["expense", "expenditure", "spending", "outlay"],
    "costs":         ["expenses", "expenditures", "spending"],
    "sales":         ["revenue", "income", "turnover", "receipts"],
    "income":        ["revenue", "earnings", "profit", "proceeds"],
    "earnings":      ["profit", "revenue", "income", "net income"],
    "ebitda":        ["operating income", "operating profit", "earnings before interest taxes"],
    "eps":           ["earnings per share", "profit per share"],
    "margin":        ["profit margin", "gross margin", "net margin"],
    "growth":        ["increase", "expansion", "rise", "gain"],
    "loss":          ["deficit", "shortfall", "decline", "negative income"],
    "assets":        ["resources", "holdings", "property", "balance sheet items"],
    "liabilities":   ["debts", "obligations", "payables"],
    "cash":          ["liquidity", "cash flow", "funds", "money"],
    "budget":        ["forecast", "plan", "spending limit", "allocation"],
    # HR / People
    "employees":     ["staff", "workers", "headcount", "workforce", "personnel", "team members"],
    "employee":      ["staff member", "worker", "team member", "personnel"],
    "salary":        ["compensation", "pay", "wage", "remuneration", "package"],
    "salaries":      ["compensation", "wages", "pay", "remuneration"],
    "pto":           ["paid time off", "vacation", "annual leave", "time off", "holiday", "leave carry forward"],
    "vacation":      ["pto", "annual leave", "paid time off", "time off", "holiday", "leave carry forward"],
    "leave":         ["vacation", "pto", "time off", "absence", "annual leave", "leave carry forward"],
    "roll":          ["rollover", "carry forward", "carried forward", "unused days"],
    "rollover":      ["carry forward", "carryover", "carried forward", "unused days", "leave balance"],
    "rollover?":     ["carry forward", "carryover", "carried forward", "unused days", "leave balance"],
    "carryover":     ["rollover", "carry forward", "carried forward", "unused days", "leave balance"],
    "benefits":      ["perks", "compensation package", "allowances", "entitlements"],
    "policy":        ["rule", "guideline", "procedure", "regulation", "standard"],
    "policies":      ["rules", "guidelines", "procedures", "regulations", "standards"],
    "onboarding":    ["orientation", "joining process", "new hire", "induction"],
    "termination":   ["dismissal", "fired", "laid off", "end of employment"],
    "performance":   ["review", "appraisal", "evaluation", "assessment"],
    "training":      ["learning", "development", "education", "course", "certification"],
    "remote":        ["work from home", "wfh", "telecommute", "distributed work"],
    "headcount":     ["number of employees", "staff count", "workforce size", "employees"],
    # Leadership / Titles
    "ceo":           ["chief executive officer", "chief executive", "president", "managing director"],
    "cto":           ["chief technology officer", "tech lead", "head of technology"],
    "cfo":           ["chief financial officer", "finance director", "head of finance"],
    "coo":           ["chief operating officer", "operations director"],
    "vp":            ["vice president", "senior director"],
    "founder":       ["co-founder", "established by", "started by", "created by"],
    # Technology
    "api":           ["application programming interface", "interface", "endpoint", "rest api"],
    "ai":            ["artificial intelligence", "machine learning", "deep learning", "neural network"],
    "ml":            ["machine learning", "artificial intelligence", "ai", "model"],
    "db":            ["database", "data store", "storage"],
    "sql":           ["database query", "relational database", "database"],
    "ui":            ["user interface", "interface", "frontend", "screen"],
    "ux":            ["user experience", "design", "usability"],
    "sdk":           ["software development kit", "library", "framework"],
    "auth":          ["authentication", "authorization", "login", "access control"],
    "deployment":    ["release", "launch", "rollout", "publish"],
    "bug":           ["issue", "defect", "error", "problem", "fix"],
    "feature":       ["functionality", "capability", "function", "option"],
    "integration":   ["connect", "plugin", "connector", "interface"],
    # Research / Academic
    "methodology":   ["method", "approach", "technique", "procedure"],
    "hypothesis":    ["assumption", "theory", "proposition", "claim"],
    "findings":      ["results", "conclusions", "outcomes", "observations"],
    "study":         ["research", "investigation", "analysis", "paper", "report"],
    "conclusion":    ["result", "finding", "outcome", "summary", "summary"],
    "abstract":      ["summary", "overview", "introduction"],
    # Products / Operations
    "price":         ["cost", "fee", "charge", "rate", "tariff"],
    "pricing":       ["cost", "fee", "rate", "charges", "tariff"],
    "product":       ["item", "offering", "solution", "service"],
    "customer":      ["client", "user", "buyer", "consumer"],
    "support":       ["help", "assistance", "service", "troubleshoot"],
    "requirement":   ["specification", "need", "prerequisite", "dependency"],
    "setup":         ["installation", "configuration", "getting started", "initialize"],
    "install":       ["setup", "configure", "deploy", "initialize"],
    # Travel / Expense
    "expense":        ["expenditure", "cost", "reimbursement", "claim", "outlay"],
    "expenses":       ["expenditures", "costs", "reimbursements", "claims"],
    "reimbursement":  ["expense claim", "repayment", "refund", "expense reimbursement"],
    "reimbursements": ["expense claims", "repayments", "refunds"],
    "travel":         ["business travel", "trip", "flight", "accommodation", "hotel"],
    "mileage":        ["distance allowance", "vehicle reimbursement", "car allowance", "per mile"],
    "per":            ["per diem", "daily allowance", "daily rate", "subsistence"],
    "receipt":        ["invoice", "proof of purchase", "documentation", "bill"],
    "receipts":       ["invoices", "proof of purchase", "documentation", "bills"],
    "allowance":      ["limit", "cap", "maximum", "entitlement", "per diem"],
    "claim":          ["reimbursement request", "expense submission", "expense form"],
    # Contractor / Vendor
    "contractor":     ["vendor", "supplier", "third-party", "consultant", "service provider"],
    "contractors":    ["vendors", "suppliers", "third-parties", "consultants"],
    "vendor":         ["supplier", "contractor", "service provider", "third-party"],
    "vendors":        ["suppliers", "contractors", "service providers"],
    "outsource":      ["third-party", "vendor", "contractor", "external provider"],
    # General
    "total":         ["sum", "aggregate", "combined", "overall", "grand total"],
    "increase":      ["growth", "rise", "gain", "improvement", "up"],
    "decrease":      ["decline", "fall", "reduction", "drop", "down"],
    "define":        ["meaning", "definition", "explanation", "what is"],
    "explain":       ["describe", "elaborate", "detail", "how does"],
    "compare":       ["difference", "versus", "contrast", "comparison"],
    "difference":    ["distinction", "comparison", "contrast", "versus"],
    "overview":      ["summary", "introduction", "description", "about"],
    "steps":         ["procedure", "process", "instructions", "guide", "how to"],
    "how":           ["steps", "process", "procedure", "method", "way"],
    "why":           ["reason", "cause", "purpose", "rationale", "explanation"],
}

_QUESTION_OPENERS = frozenset({
    'what', 'how', 'when', 'where', 'who', 'why', 'which',
    'is', 'are', 'can', 'does', 'do', 'define', 'explain',
})


_QUERY_PHRASE_REWRITES: tuple[tuple[tuple[str, ...], list[str]], ...] = (
    (
        ("vacation", "days"),
        ["PTO", "paid time off", "annual leave", "leave carry forward"],
    ),
    (
        ("vacation", "roll"),
        ["PTO rollover", "paid time off carry forward", "unused vacation days", "leave carry forward"],
    ),
    (
        ("pto", "roll"),
        ["PTO rollover", "paid time off carry forward", "unused PTO days", "leave carry forward"],
    ),
    (
        ("leave", "roll"),
        ["leave carry forward", "annual leave rollover", "unused leave balance"],
    ),
)


def _query_phrase_rewrites(question: str) -> list[str]:
    """Return high-value phrase rewrites for terms embeddings often blur."""
    q_lower = question.lower()
    rewrites: list[str] = []
    seen: set[str] = set()

    for required_terms, expansions in _QUERY_PHRASE_REWRITES:
        if all(term in q_lower for term in required_terms):
            for expansion in expansions:
                key = expansion.lower()
                if key not in seen and key not in q_lower:
                    seen.add(key)
                    rewrites.append(expansion)

    return rewrites


def _expand_query(question: str) -> str:
    """Expand query with synonyms and semantic variants for improved recall.

    Applies to ALL query lengths (previously capped at 8 words).
    Synonym terms are appended to the query string so the embedding vector
    covers a wider semantic area — relevant chunks using alternate terminology
    (e.g. 'PTO' for a 'vacation' query) will now rank higher.
    """
    q      = question.strip().rstrip('?.,')
    q_lower = q.lower()
    words  = q_lower.split()

    # ── Collect synonym expansions ─────────────────────────────────────────────
    seen_terms: set[str] = set(words)
    extra_terms: list[str] = []

    for rewrite in _query_phrase_rewrites(q):
        extra_terms.append(rewrite)
        seen_terms.update(rewrite.lower().split())

    for word in words:
        clean = word.strip('?.,!;:\'\"')
        for syn in _QUERY_SYNONYMS.get(clean, []):
            # Take the first word of multi-word synonyms (keeps embed query concise)
            syn_key = syn.split()[0].lower()
            if syn_key not in seen_terms and len(syn_key) > 2:
                extra_terms.append(syn)
                seen_terms.update(syn.lower().split())
            if len(extra_terms) >= 20:
                break
        if len(extra_terms) >= 20:
            break

    parts: list[str] = [q]
    if extra_terms:
        # Append synonym terms as space-separated tokens after the original query
        parts.append(' '.join(extra_terms))

    # ── Generic semantic rephrasing for short queries ─────────────────────────
    if len(words) <= 10:
        has_opener = any(q_lower.startswith(w + ' ') for w in _QUESTION_OPENERS)
        if has_opener:
            parts.append(f"information about {q}")
        else:
            parts.extend([f"what is {q}", f"information about {q}"])

    expanded = ' '.join(parts)
    if expanded != question:
        pass   # caller logs the expansion when it differs
    return expanded


def _generate_search_variants(question: str, intent: str) -> list[str]:
    """Generate 3–6 semantically distinct query variants for multi-vector retrieval.

    Each variant covers a different semantic angle so the combined search finds
    chunks that a single query string would miss due to vocabulary mismatch.
    E.g. "What is Azure AI Foundry?" produces:
      ["What is Azure AI Foundry?", "Azure AI Foundry", "AI Foundry",
       "Microsoft AI platform developer AI platform AI application platform"]
    """
    import re as _re

    q       = question.strip()
    q_lower = q.lower().rstrip('?.,')
    variants: list[str] = [q]

    # ── V2: Core noun phrase (strip leading question words) ───────────────────
    core = q
    for opener in (
        'what is ', 'what are ', 'what does ', 'what do ',
        'who is ', 'who are ',
        'define ', 'explain ', 'describe ',
        'tell me about ', 'give me information on ',
        'how does ', 'how do ', 'how is ',
    ):
        if q_lower.startswith(opener):
            core = q[len(opener):].strip().rstrip('?.,')
            if core and core.lower() not in (v.lower() for v in variants):
                variants.append(core)
            break

    # ── V3: Extracted entity names (bare proper nouns / acronyms) ────────────
    entities = _extract_query_entities(q)
    for entity in entities[:2]:
        entity = entity.strip()
        if entity and entity.lower() not in (v.lower() for v in variants):
            variants.append(entity)

    # ── V4: Synonym-expanded single query (existing _expand_query output) ─────
    expanded = _expand_query(q)
    if expanded.lower() != q_lower and expanded.lower() not in (v.lower() for v in variants):
        variants.append(expanded)

    # ── V5: Intent-specific semantic alternatives ──────────────────────────────
    if intent in ('definition', 'explanation') and core and core != q:
        alt = f"{core} overview features capabilities"
        if alt.lower() not in (v.lower() for v in variants):
            variants.append(alt)

    elif intent == 'financial':
        # Strip year markers so we also find chunks without an explicit year
        no_year = _re.sub(
            r'\b(20\d\d|FY\s*\d{2,4}|fiscal\s+year\s+\d{4}|Q[1-4]\s+20\d\d)\b',
            '', q, flags=_re.IGNORECASE,
        ).strip(' ,.')
        if no_year and no_year.lower() not in (v.lower() for v in variants) and len(no_year) > 5:
            variants.append(no_year)

    elif intent in ('shortfact', 'oneword', 'person') and entities:
        # Person/title queries: add a role-focused variant
        role_alt = f"{entities[0]} role position title responsibilities"
        if role_alt.lower() not in (v.lower() for v in variants):
            variants.append(role_alt)

    # ── V5b: Compliance fan-out (one variant per detected policy domain) ─────
    # Multi-policy compliance questions ("employee works remotely 5d, password
    # 8 chars, claim after 45 days, …") collapse into a single embedding that
    # cannot represent all four policy domains at once. We add a focused
    # variant per detected domain so every policy contributes candidates.
    if intent == 'compliance':
        for domain_variant in _compliance_domain_variants(q):
            if domain_variant.lower() not in (v.lower() for v in variants):
                variants.append(domain_variant)

    # ── V6: Acronym-expanded variant ──────────────────────────────────────────
    words = q.split()
    expanded_words: list[str] = []
    any_expanded = False
    for word in words:
        clean = word.strip('?.,!;:\'\"').lower()
        syns  = _QUERY_SYNONYMS.get(clean, [])
        if syns:
            expanded_words.append(syns[0])
            any_expanded = True
        else:
            expanded_words.append(word)
    if any_expanded:
        acronym_variant = ' '.join(expanded_words)
        if acronym_variant.lower() not in (v.lower() for v in variants):
            variants.append(acronym_variant)

    # ── Deduplicate (case-insensitive) ────────────────────────────────────────
    # Compliance questions need a higher cap because each policy domain
    # contributes its own variant; clipping to 6 would drop policies.
    seen: set[str] = set()
    result: list[str] = []
    for v in variants:
        key = v.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(v.strip())

    cap = 12 if intent == 'compliance' else 6
    return result[:cap]


# ── Compliance domain detection ──────────────────────────────────────────────
# Each entry maps signal keywords found in the question to a focused query
# that retrieves chunks from that policy domain. Keep keywords lowercase.
_COMPLIANCE_DOMAINS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("remote work", "remotely", "work from home", "wfh", "telecommute"),
        "remote work policy days per week eligibility approval"),
    (("password", "credential", "passphrase"),
        "password policy minimum length complexity rotation expiry"),
    (("mfa", "multi-factor", "two-factor", "2fa", "multifactor"),
        "multi-factor authentication policy required exceptions"),
    (("reimburs", "expense claim", "expense report", "claim submission"),
        "travel expense reimbursement policy submission deadline days bills receipts approval"),
    (("travel", "trip", "business travel", "international"),
        "travel policy approval international director domestic booking"),
    (("leave", "vacation", "pto", "time off", "sick"),
        "leave policy entitlement approval notice"),
    (("data ", "data protection", "data privacy", "gdpr", "phi", "pii"),
        "data protection policy retention classification access"),
    (("security incident", "breach", "vulnerability", "phishing"),
        "security incident policy reporting response disclosure"),
    (("access ", "permission", "authorization"),
        "access control policy least privilege approval review"),
    (("training", "certification", "onboarding"),
        "training policy mandatory completion frequency"),
)


def _compliance_domain_variants(question_lower: str) -> list[str]:
    """Return focused per-policy queries for every domain detected in the question."""
    variants: list[str] = []
    for keywords, variant in _COMPLIANCE_DOMAINS:
        if any(kw in question_lower for kw in keywords):
            variants.append(variant)
    return variants


# ── Pronouns and reference words that signal a follow-up question ─────────────
_PRONOUN_REF_WORDS = frozenset({
    'it', 'its', 'they', 'them', 'their', 'this', 'that',
    'these', 'those', 'he', 'him', 'his', 'she', 'her', 'hers',
})
_FOLLOWUP_PHRASES = (
    'the company', 'the product', 'the platform', 'the system',
    'the tool', 'the service', 'the application', 'the app',
    'the project', 'the feature', 'the software', 'the library',
    'the framework', 'the technology', 'the solution',
)
_AMBIGUOUS_REFERENCE_PATTERNS = (
    "this action", "that action", "the action",
    "this rule", "that rule", "the rule",
    "this policy", "that policy", "the policy",
    "this requirement", "that requirement", "the requirement",
    "this exception", "that exception", "the exception",
)


def _has_pronoun_reference(question: str) -> bool:
    """Return True if the question uses pronouns or phrases that refer to prior context."""
    q_lower = question.lower().strip()
    words = set(q_lower.split())
    if words & _PRONOUN_REF_WORDS:
        return True
    return any(phrase in q_lower for phrase in _FOLLOWUP_PHRASES)


def _extract_history_context_terms(recent_history: list[dict], limit: int = 5) -> list[str]:
    """Extract lightweight topic hints from prior turns for follow-up resolution.

    Entity extraction catches proper nouns, but policy follow-ups often refer to
    lowercase topics like "remote work" or "password policy". This helper keeps
    short noun-like phrases from recent user turns without calling an LLM.
    """
    import re as _re

    if not recent_history:
        return []

    phrases: list[str] = []
    prior_user_texts = [
        (h.get("content") or "")
        for h in recent_history
        if h.get("role") == "user"
    ]

    opener_re = _re.compile(
        r"^\s*(tell me about|what is|what are|explain|describe|summarize|summarise|"
        r"give me (?:an? )?(?:overview|summary) of|show me)\s+",
        _re.IGNORECASE,
    )
    stop = set(_STOP_WORDS) | {
        "would", "could", "should", "allowed", "allow", "approved", "approve",
        "conditions", "met", "before", "after", "mentioned", "rule", "policy",
        "action", "requirement", "exception", "exceptions",
    }

    for text in reversed(prior_user_texts[-3:]):
        cleaned = opener_re.sub("", text).strip(" ?.!:;")
        if not cleaned:
            continue

        # Prefer quoted terms and compact adjective+noun phrases.
        phrases.extend(_re.findall(r'"([^"]{2,80})"', cleaned))
        phrases.extend(_re.findall(r"'([^']{2,80})'", cleaned))

        words = [
            w.lower()
            for w in _re.findall(r"[A-Za-z][A-Za-z0-9-]*", cleaned)
            if len(w) > 2 and w.lower() not in stop
        ]
        if not words:
            continue

        if len(words) >= 2:
            phrases.append(" ".join(words[:3]))
        else:
            phrases.append(words[0])

    seen: set[str] = set()
    result: list[str] = []
    for phrase in phrases:
        normalized = " ".join(phrase.split()).strip()
        key = normalized.lower()
        if len(key) >= 3 and key not in seen:
            seen.add(key)
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _needs_ambiguity_clarification(question: str, recent_history: list[dict]) -> tuple[bool, str]:
    """Detect vague referential policy questions that cannot be resolved safely."""
    q_lower = " ".join(question.lower().strip().split())
    if not any(pattern in q_lower for pattern in _AMBIGUOUS_REFERENCE_PATTERNS):
        return False, ""

    if _extract_query_entities(question):
        return False, ""

    if _extract_history_context_terms(recent_history):
        return False, ""

    if "action" in q_lower:
        return True, "Please specify which action you are referring to so I can evaluate it against the document."
    if "rule" in q_lower:
        return True, "Please specify which rule you are referring to so I can evaluate it against the document."
    if "policy" in q_lower:
        return True, "Please specify which policy you are referring to so I can evaluate it against the document."
    if "requirement" in q_lower:
        return True, "Please specify which requirement you are referring to so I can evaluate it against the document."
    return True, "Please specify which action, rule, or policy you are referring to."


def _extract_query_entities(question: str) -> list[str]:
    """Extract entity names (proper nouns, CamelCase, acronyms, quoted terms) from the question.

    These are used to run a targeted ILIKE search that catches exact entity mentions
    even when the cosine similarity is low.
    """
    import re as _re
    candidates: list[str] = []

    # Quoted terms  (highest confidence entity signals)
    candidates += _re.findall(r'"([^"]{2,})"', question)
    candidates += _re.findall(r"'([^']{2,})'", question)

    # CamelCase / PascalCase — e.g. "BookWrench", "PostgreSQL"
    candidates += _re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b', question)

    # ALL-CAPS acronyms (≥ 3 chars) — e.g. "RAG", "PDF", "JWT"
    candidates += _re.findall(r'\b[A-Z]{3,}\b', question)

    # Capital-initial multi-word proper nouns run (2–4 consecutive cap words)
    words = question.split()
    run: list[str] = []
    for w in words:
        stripped = w.rstrip('.,?!')
        if stripped and stripped[0].isupper() and stripped.lower() not in _STOP_WORDS:
            run.append(stripped)
        else:
            if len(run) >= 2:
                candidates.append(' '.join(run))
            run = []
    if len(run) >= 2:
        candidates.append(' '.join(run))

    # Deduplicate, drop stopwords, enforce minimum length
    seen: set[str] = set()
    result: list[str] = []
    for e in candidates:
        e = e.strip()
        if len(e) >= 3 and e.lower() not in _STOP_WORDS and e not in seen:
            seen.add(e)
            result.append(e)
    return result


def _contextualize_query(question: str, recent_history: list[dict]) -> str:
    """Rewrite a follow-up question by injecting entity context from prior turns.

    Resolves pronoun references like "Who founded it?" → "Who founded it? BookWrench"
    using key entity names extracted from the most recent user message(s).

    Only modifies the query used for embedding — the original question is still
    sent as-is to the LLM.
    """
    if not recent_history or not _has_pronoun_reference(question):
        return question

    import re as _re

    prev_user_msgs = [h for h in recent_history if h.get('role') == 'user']
    if not prev_user_msgs:
        return question

    # Extract entities from the last 1-2 user turns
    entities: list[str] = []
    for msg in reversed(prev_user_msgs[-2:]):
        text = msg.get('content', '')
        # CamelCase proper nouns
        entities += _re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b', text)
        # ALL-CAPS acronyms
        entities += _re.findall(r'\b[A-Z]{3,}\b', text)
        # Quoted terms
        entities += _re.findall(r'"([^"]{2,})"', text)
        entities += _re.findall(r"'([^']{2,})'", text)

    # Also grab key nouns from the last assistant reply (e.g., it might name the entity)
    prev_ai_msgs = [h for h in recent_history if h.get('role') == 'assistant']
    if prev_ai_msgs:
        last_ai = prev_ai_msgs[-1].get('content', '')[:500]
        entities += _re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b', last_ai)

    entities += _extract_history_context_terms(recent_history)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in entities:
        if e not in seen and e.lower() not in _STOP_WORDS:
            seen.add(e)
            unique.append(e)

    if not unique:
        return question

    context_hint = ' '.join(unique[:5])
    rewritten = f"{question} {context_hint}"
    logger.info(f"[RAG] Query contextualized: {question!r} → {rewritten!r}")
    return rewritten


async def _entity_search(
    entities: list[str],
    user_id: uuid.UUID,
    db: AsyncSession,
    scope_type: str = "all",
    scope_id: uuid.UUID | None = None,
    scope_name: str | None = None,
) -> list[tuple]:
    """ILIKE-based targeted search for specific entity names / terms.

    Returns (DocumentChunk, Document) pairs where the chunk content contains
    the entity string (case-insensitive). This catches exact entity mentions
    that cosine similarity might miss due to vocabulary mismatch.
    """
    if not entities:
        return []

    seen_ids: set[uuid.UUID] = set()
    results: list[tuple] = []

    for entity in entities[:6]:
        if len(entity) < 3:
            continue
        try:
            stmt = (
                select(DocumentChunk, Document)
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(Document.user_id == user_id)
                .where(Document.status == DocumentStatus.indexed)
                .where(DocumentChunk.embedding.is_not(None))
                .where(DocumentChunk.content.ilike(f"%{entity}%"))
            )
            if scope_type == "folder" and scope_id:
                stmt = stmt.where(Document.folder_id == scope_id)
            elif scope_type == "document" and scope_id:
                stmt = stmt.where(Document.id == scope_id)
            elif scope_type == "domain" and scope_name:
                stmt = stmt.where(Document.domain_name == scope_name)

            stmt = stmt.limit(settings.TOP_K_CHUNKS)
            rows = await db.execute(stmt)
            for chunk, doc in rows.all():
                if chunk.id not in seen_ids:
                    seen_ids.add(chunk.id)
                    results.append((chunk, doc))
        except Exception as exc:
            logger.warning(f"[RAG] Entity search failed for {entity!r}: {exc}")

    return results


async def _load_recent_turns(
    session_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 6,
) -> list[dict]:
    """Load the most recent conversation turns for query contextualization.

    Returns oldest-first list of {role, content} dicts.
    Called BEFORE saving the current user message so the history is prior context only.
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    rows = list(reversed(rows))
    return [
        {"role": m.role, "content": m.content[:600]}
        for m in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Evidence conflict detection
# ─────────────────────────────────────────────────────────────────────────────

import re as _re

# Proper-noun name: two or more title-cased words (handles middle initials too)
_NAME_RE = _re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+)+)\b')
# Monetary / large numeric value (captures $245B, $281.7 billion, 245,000, etc.)
_MONEY_RE = _re.compile(
    r'(?:[\$€£¥]\s*)?'
    r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
    r'(?:\s*(?:billion|million|trillion|thousand|bn|mn|B|M|T|K))?'
    r'(?:\s*(?:USD|EUR|GBP|INR))?',
    _re.IGNORECASE,
)
# Year labels that disambiguate financial periods
_YEAR_RE = _re.compile(r'\b(?:FY|fiscal year\s*)?(20\d{2}|19\d{2})\b', _re.IGNORECASE)

# Role keywords that signal an executive-lookup question
_EXEC_ROLE_KW = frozenset({
    'ceo', 'cfo', 'cto', 'coo', 'cso', 'cpo', 'cmo',
    'chairman', 'chair', 'president', 'founder', 'co-founder',
    'chief executive', 'chief financial', 'chief technology',
    'chief operating', 'chief product', 'chief marketing',
    'director', 'head of', 'vp of', 'vice president',
    'managing director', 'executive director',
})
# Common capitalized non-name phrases to skip
_NAME_SKIP_PREFIXES = frozenset({
    'The ', 'This ', 'These ', 'Those ', 'Our ', 'Their ', 'Its ',
    'For ', 'In ', 'As ', 'On ', 'At ', 'By ', 'Of ', 'To ',
    'Mr ', 'Ms ', 'Dr ', 'Jr ', 'Sr ',
    'Annual ', 'Fiscal ', 'Total ', 'Net ', 'Gross ',
})


def _is_person_question(question: str) -> bool:
    q = question.lower()
    return (
        any(p in q for p in ('who is', 'who was', 'who are', 'who serves', "who's"))
        or any(kw in q for kw in _EXEC_ROLE_KW)
    )


# Canonical role map: question keyword → display label
_ROLE_CANONICAL: dict[str, str] = {
    'ceo':                    'CEO',
    'chief executive officer':'CEO',
    'chief executive':        'CEO',
    'cfo':                    'CFO',
    'chief financial officer':'CFO',
    'chief financial':        'CFO',
    'cto':                    'CTO',
    'chief technology officer':'CTO',
    'chief technology':       'CTO',
    'coo':                    'COO',
    'chief operating officer':'COO',
    'chief operating':        'COO',
    'cso':                    'CSO',
    'cpo':                    'CPO',
    'cmo':                    'CMO',
    'chairman':               'Chairman',
    'chair':                  'Chairman',
    'president':              'President',
    'founder':                'Founder',
    'co-founder':             'Co-Founder',
    'director':               'Director',
    'managing director':      'Managing Director',
    'executive director':     'Executive Director',
    'vp':                     'VP',
    'vice president':         'Vice President',
    'head of':                'Head',
}

# Full-form expansions per canonical role (for pattern matching inside chunks)
_ROLE_FULL_FORMS: dict[str, list[str]] = {
    'CEO':               ['chief executive officer', 'chief executive', 'ceo'],
    'CFO':               ['chief financial officer', 'chief financial', 'cfo'],
    'CTO':               ['chief technology officer', 'chief technology', 'cto'],
    'COO':               ['chief operating officer', 'chief operating', 'coo'],
    'Chairman':          ['chairman', 'chair of the board', 'chair'],
    'President':         ['president'],
    'Founder':           ['founder', 'co-founder'],
    'VP':                ['vice president', 'vp'],
    'Director':          ['director'],
    'Managing Director': ['managing director'],
}


def _extract_role_from_question(question: str) -> str | None:
    """Return the canonical role label for the role being asked about, or None."""
    q = question.lower()
    # Longer phrases first to avoid partial matches (e.g. 'chair' before 'chairman')
    for kw in sorted(_ROLE_CANONICAL, key=len, reverse=True):
        if kw in q:
            return _ROLE_CANONICAL[kw]
    return None


def _extract_name_for_role(text: str, role: str | None) -> str | None:
    """
    Return a person name that is EXPLICITLY assigned ``role`` in ``text``.

    Patterns recognised (case-insensitive):
      "[Name] is [the] {role}"
      "{role}[,/:] [Name]"
      "[Name], {role}"
      "appointed/named/elected [Name] as {role}"

    Falls back to ``_extract_primary_name(text)`` only when ``role`` is None
    (non-role person questions such as "Who authored this?").
    """
    if role is None:
        return _extract_primary_name(text)

    name_pat = r'([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+)+)'
    variants  = [role] + _ROLE_FULL_FORMS.get(role, [])

    for rv in variants:
        rv_esc = _re.escape(rv)
        patterns = [
            # Name is [the/a/our] Role
            rf'{name_pat}\s+(?:is|was|serves\s+as|served\s+as)\s+(?:the\s+|a\s+|our\s+)?{rv_esc}',
            # Role[,/: ] Name
            rf'{rv_esc}\s*[,/:\s]{{1,3}}{name_pat}',
            # Name, Role
            rf'{name_pat}\s*,\s*{rv_esc}',
            # appointed/named/elected Name as Role
            rf'(?:appointed|named|elected|hired|promoted)\s+{name_pat}\s+as\s+{rv_esc}',
            # Name (Role)
            rf'{name_pat}\s*\(\s*{rv_esc}\s*\)',
        ]
        for pat in patterns:
            m = _re.search(pat, text, _re.IGNORECASE)
            if m:
                for grp in m.groups():
                    if grp and _re.match(r'^[A-Z][a-z]+', grp.strip()):
                        name = grp.strip()
                        if not any(name.startswith(p) for p in _NAME_SKIP_PREFIXES):
                            return name

    return None


def _extract_primary_name(text: str) -> str | None:
    """Return the first plausible person name from ``text``."""
    for m in _NAME_RE.finditer(text):
        name = m.group(1)
        if not any(name.startswith(p) for p in _NAME_SKIP_PREFIXES):
            return name
    return None


def _extract_primary_value(text: str) -> str | None:
    """Return the first significant monetary/numeric token from ``text``."""
    for m in _MONEY_RE.finditer(text):
        v = m.group(0).strip()
        # Require at least one digit and be longer than a bare year like "2025"
        if v and _re.search(r'\d', v) and len(v) > 3:
            return v
    return None


def _year_label(text: str) -> str | None:
    """Return the first fiscal/calendar year label found, e.g. '2024'."""
    m = _YEAR_RE.search(text)
    return m.group(1) if m else None


def _detect_conflicts(
    question: str,
    chunks: list[tuple],
    intent: str,
) -> dict | None:
    """
    Role-aware, precision conflict detection.

    Person / role questions
    ─────────────────────────────────────────────────────────
    Extracts the specific role from the question (CEO, CFO, Chairman …).
    A candidate is only registered when the chunk text EXPLICITLY assigns
    that role to a named person.  Multiple names appearing in the same
    chunk for unrelated reasons (board lists, quoted authors, etc.) are
    intentionally ignored.  Conflict is declared ONLY when two distinct
    names are each explicitly assigned the same role.

    Numeric / financial questions
    ─────────────────────────────────────────────────────────
    Extracts the primary monetary/numeric value per chunk.
    Different fiscal years → NOT a conflict (expected period data).
    Conflict only when the same period shows two different values.

    Never runs for: summary | comparison | analytical | explanation | list |
    table | chart | process | definition — those intents are multi-value by
    nature and false-positive rates are too high.
    """
    if not chunks or len(chunks) < 2:
        return None

    conflict_intents = {'oneword', 'shortfact', 'numerical', 'financial', 'person'}
    person_q = _is_person_question(question)

    if intent not in conflict_intents and not person_q:
        return None

    # For person/role questions: extract the SPECIFIC role being queried
    queried_role: str | None = None
    if person_q:
        queried_role = _extract_role_from_question(question)

    top = chunks[:5]
    candidates: list[dict] = []

    for idx, (chunk, doc, dist) in enumerate(top, 1):
        content = (chunk.content or '').strip()
        source  = doc.original_name
        page    = str(chunk.page_number) if chunk.page_number else None
        score   = round(1.0 - float(dist), 4)

        if person_q:
            value = _extract_name_for_role(content, queried_role)
        else:
            value = _extract_primary_value(content)

        if value:
            candidates.append({
                "ref":     idx,
                "value":   value,
                "year":    _year_label(content),
                "source":  source,
                "page":    page,
                "score":   score,
                "excerpt": content[:250].replace('\n', ' '),
            })

    if len(candidates) < 2:
        # Fewer than 2 role-matched names → no conflict possible
        if person_q and queried_role:
            logger.debug(
                f"[Conflict] No conflict — fewer than 2 chunks explicitly assign "
                f"{queried_role!r}  (found {len(candidates)} role-matched candidate(s))"
            )
        return None

    v0 = candidates[0]["value"].strip().lower()
    v1 = candidates[1]["value"].strip().lower()
    if v0 == v1:
        return None  # Same answer in both chunks — consensus, not conflict

    # Numeric: different fiscal years = period data, not a contradiction
    if not person_q:
        y0, y1 = candidates[0].get("year"), candidates[1].get("year")
        if y0 and y1 and y0 != y1:
            logger.info(
                f"[Conflict] Different fiscal years ({y0} vs {y1}) — "
                "treating as period data, not a conflict."
            )
            return None

    role_tag = f" for role={queried_role!r}" if queried_role else ""
    logger.warning(
        f"[Conflict] Genuine contradiction detected{role_tag}  "
        f"intent={intent}  "
        f"values={[c['value'] for c in candidates[:2]]}  "
        f"question={question!r}"
    )
    return {"candidates": candidates[:3], "role": queried_role}


def _format_conflict_response(conflict: dict, question: str) -> str:
    """Render a human-readable conflict notice with both sources."""
    candidates = conflict["candidates"]
    lines = [
        f"**{NO_CONFLICT_MSG}**\n",
        "The retrieved excerpts provide different answers for this question. "
        "Both are shown below — no merging or guessing has been applied:\n",
    ]
    for c in candidates:
        page_str = f", Page {c['page']}" if c["page"] else ""
        lines.append(f"**Excerpt [{c['ref']}]:** {c['value']}")
        lines.append(f"*Source: {c['source']}{page_str}*")
        if c.get("excerpt"):
            lines.append(f"> …{c['excerpt'][:150]}…")
        lines.append("")

    lines.append(
        "**Recommendation:** Review the source documents directly to determine "
        "which value is correct for your specific question."
    )
    return "\n".join(lines)


# Shared directive used for analytical and general (reasoning) intents.
_MULTI_HOP_DIRECTIVE = (
    "RESPONSE FORMAT — ENTERPRISE RESEARCH ANALYST\n\n"
    "You are an Enterprise Research Analyst. Answer only from retrieved evidence.\n\n"
    "For reasoning questions:\n"
    "1. Combine information from multiple chunks.\n"
    "2. Explain relationships.\n"
    "3. Do not copy chunks.\n"
    "4. Generate insights only if evidence supports them.\n\n"
    "━━━ OUTPUT FORMAT ━━━\n"
    "**Question:** [restate the user's question]\n\n"
    "**Answer:**\n"
    "[Synthesized answer with inline [N] citations on every factual claim.]\n\n"
    "**Supporting Evidence:**\n"
    "- [specific fact from context] [N]\n"
    "- [specific fact from context] [N]\n\n"
    "**Sources:**\n"
    "[N] [Document name], Page [page number]\n\n"
    "If evidence is insufficient:\n"
    "\"I could not find enough information in the retrieved documents.\"\n\n"
)


def _build_system_prompt(
    scope_type: str,
    scope_name: str | None,
    mode: str = "auto",
    complexity: str = "medium",
    intent: str = "general",
) -> str:
    """Prepend a scope header AND mode instruction to the base system prompt.

    Order: length hint → intent directive → scope header → mode instruction → base SYSTEM_PROMPT.
    """
    parts: list[str] = []

    # ── Intent-first format directive (auto mode only) ───────────────────────
    # These appear at the very top of the assembled prompt so they override
    # the model's default format choices. Each directive maps directly to one
    # of the 16 TYPE blocks in the SYSTEM_PROMPT.
    if mode == "auto":
        if intent == "oneword":
            parts.append(
                "RESPONSE FORMAT — TYPE 1: ONE-WORD ANSWER\n"
                "Return ONLY the exact answer value + [N]. One line. Nothing else.\n"
                "CORRECT: 'Satya Nadella [1]'  |  '1975 [2]'  |  '$245B [3]'\n"
                "WRONG: 'The CEO is...'  |  'According to...'  |  Any sentence.\n"
                "No Related Questions. No headers.\n\n"
            )
        elif intent == "numerical":
            parts.append(
                "RESPONSE FORMAT — TYPE 3: NUMERICAL METRIC\n"
                "Lead with the exact value on the FIRST LINE, then source. Nothing before it.\n\n"
                "━━━ OUTPUT FORMAT (use exactly) ━━━\n\n"
                "**[Metric Name]:** [Exact Value] [N]\n\n"
                "**Source:** [Document Name], Page [page number]\n\n"
                "RULES:\n"
                "• VERBATIM — never round, estimate, or paraphrase the number.\n"
                "• No preamble ('According to...', 'The document states...').\n"
                "• No Related Questions. No headers beyond the ones above.\n"
                "• If multiple excerpts give different values → list each with its citation.\n\n"
            )
        elif intent == "person":
            parts.append(
                "RESPONSE FORMAT — ROLE / ENTITY LOOKUP\n\n"
                "STEP 1 — Scan ALL excerpts and find the one that EXPLICITLY assigns "
                "the requested role (CEO, CFO, Chairman, etc.) to a named person.\n"
                "STEP 2 — State the answer immediately on the first line. No preamble.\n"
                "STEP 3 — Cite the source excerpt inline.\n\n"
                "━━━ OUTPUT FORMAT (use exactly) ━━━\n\n"
                "**Answer:** [Full Name] is the [Role Title]. [N]\n\n"
                "**Evidence:** \"[exact phrase from the document that assigns the role]\" [N]\n\n"
                "**Source:** [Document Name], Page [page number]\n\n"
                "**Confidence:** High | Medium | Low\n\n"
                "RULES:\n"
                "• Return ONLY the person explicitly assigned that role in the retrieved text.\n"
                "• Ignore all other names that appear in the same chunk for different reasons.\n"
                "• If no excerpt explicitly assigns the role → return: "
                "\"The requested information is not available in the uploaded documents.\"\n"
                "• Never infer, guess, or use external knowledge.\n\n"
            )
        elif intent == "shortfact" or (complexity == "fact" and intent not in ("numerical", "oneword")):
            parts.append(
                "RESPONSE FORMAT — TYPE 2: SHORT FACT\n"
                "Lead with a CONCISE DIRECT ANSWER on the very first line. No preamble.\n\n"
                "━━━ OUTPUT FORMAT (use exactly) ━━━\n\n"
                "[Direct answer in one sentence.] [N]\n\n"
                "**Source:** [Document Name], Page [page number]\n\n"
                "EXAMPLES:\n"
                "  Q: How often do backups occur?\n"
                "  A: Every 6 hours. [1]\n"
                "  Source: Backup Policy, Page 4\n\n"
                "  Q: What is the notice period for termination?\n"
                "  A: 30 days written notice is required. [2]\n"
                "  Source: Employment Agreement, Page 7\n\n"
                "RULES:\n"
                "• Answer first — no 'According to...', 'The document states...', or any opener.\n"
                "• Inline [N] citations on every factual claim.\n"
                "• If multiple excerpts confirm the same fact — combine citations [N][M].\n"
                "• No bullet lists. No headers. No Related Questions.\n\n"
            )
        elif intent == "definition":
            parts.append(
                "RESPONSE FORMAT — TYPE 4: DEFINITION\n"
                "Use this exact structure (skip sections with no context):\n"
                "**Definition:** [one-sentence definition] [N]\n"
                "**Purpose:** [what it is used for] [N]\n"
                "**Key Characteristics:**\n"
                "- [from context] [N]\n"
                "**Example:** [from context if available] [N]\n\n"
            )
        elif intent == "explanation":
            parts.append(
                "RESPONSE FORMAT — TYPE 5: EXPLANATION\n"
                "Use this exact structure (skip any section with no supporting context):\n"
                "**Overview:** [one-sentence summary from context] [N]\n"
                "**Key Concepts:**\n"
                "- **[Concept]:** [explanation from context] [N]\n"
                "**How It Works:** [from context — combine evidence across excerpts] [N]\n"
                "**Examples:** [from context only — never fabricate] [N]\n"
                "Combine information from multiple excerpts freely. "
                "Explain relationships, not just individual facts.\n\n"
            )
        elif intent == "summary":
            parts.append(
                "RESPONSE FORMAT — DOCUMENT SUMMARIZER\n\n"
                "Read ALL retrieved chunks and produce a coherent summary that "
                "aggregates content from across the entire retrieved set. Do not "
                "narrow to a single chunk — every retrieved excerpt contributes.\n\n"
                "━━━ LENGTH CONTROL ━━━\n"
                "If the user's question specifies a length, honour it exactly:\n"
                "  • 'in 50 words'  / '~50 words'  → target 45–55 words\n"
                "  • 'in 100 words' / '~100 words' → target 90–110 words\n"
                "  • 'in 200 words' / '~200 words' → target 180–220 words\n"
                "  • 'detailed' / 'comprehensive' / 'in depth' → 300–500 words\n"
                "  • No length specified → 150–250 words\n"
                "Count words; never exceed the upper bound. Drop low-value detail "
                "before trimming citations.\n\n"
                "━━━ SUMMARY RULES ━━━\n"
                "1. Use ALL retrieved chunks — summary quality is coverage-driven.\n"
                "2. NEVER refuse to summarize. Even if the chunks look broad or "
                "   tangentially related, produce a summary of what they DO contain. "
                "   Do NOT output 'documents do not contain enough information' for "
                "   a summary request — that phrase is forbidden in this format.\n"
                "3. Remove duplicate information — if the same fact appears in multiple "
                "   chunks, state it once with all relevant citations [N][M].\n"
                "4. Use neutral language. No promotional phrases.\n"
                "5. Every factual claim must carry an inline [N] citation.\n"
                "6. Skip any section that has no supporting context — never fabricate.\n"
                "7. Preserve numbered lists and ordered steps as numbered lists; "
                "   never collapse a step-by-step process into prose unless explicitly asked.\n\n"
                "━━━ OUTPUT STRUCTURE ━━━\n"
                "Use EXACTLY these section headers:\n\n"
                "# Executive Summary\n"
                "[2–3 sentence overview of the most important findings] [N]\n\n"
                "# Key Points\n"
                "• [key point from context] [N]\n"
                "• [key point from context] [N]\n"
                "• [key point from context] [N]\n"
                "(3–6 bullets maximum)\n\n"
                "# Important Metrics\n"
                "• [Metric name]: [exact value from context] [N]\n"
                "(List Revenue, Operating Income, Growth, and any other numeric metrics found)\n\n"
                "# Conclusion\n"
                "[1–2 sentences synthesising the overall picture from the evidence] [N]\n\n"
            )
        elif intent == "comparison":
            parts.append(
                "RESPONSE FORMAT — COMPARISON ANSWER ENGINE\n\n"
                "You are a Dedicated Comparison Answer Engine. Produce a structured "
                "multi-period comparison report from the retrieved document excerpts.\n\n"
                "━━━ COMPARISON RULES ━━━\n"
                "1. NEVER output a bare dash \"-\" in any table cell. "
                "   If a value is missing, write exactly: Not found in retrieved documents\n"
                "2. Only compare metrics that are directly related — never mix unrelated metrics "
                "   (e.g. do not put headcount alongside revenue in the same Change cell).\n"
                "3. For every metric where BOTH sides have numeric values with IDENTICAL units:\n"
                "   a. Calculate the absolute difference (new − old).\n"
                "   b. Calculate percentage change: ((new − old) / old × 100), rounded to 1 decimal.\n"
                "   c. Prefix with ▲ for increase, ▼ for decrease.\n"
                "4. If only ONE side exists for a metric, show its value and write "
                "   'Not found in retrieved documents' for the missing side. Do NOT generate "
                "   a Change value — write 'N/A'.\n"
                "5. CHARTS: only generate a chart block when BOTH sides contain numeric values "
                "   AND the units are identical. If one period is unavailable, skip the chart.\n"
                "6. Copy all numbers VERBATIM — never round, estimate, or infer.\n"
                "7. Every table cell containing a number must carry an inline [N] citation.\n\n"
                "━━━ OUTPUT STRUCTURE ━━━\n"
                "Use EXACTLY these section headers:\n\n"
                "## Executive Summary\n"
                "2–4 sentences on the most important findings and overall direction [N].\n\n"
                "## Comparison Table\n"
                "| Metric | [Period A] | [Period B] | Change |\n"
                "|--------|------------|------------|--------|\n"
                "| [metric from context] | [value] [N] | [value] [N] | ▲/▼ X% (±$Y) or N/A |\n"
                "Include ALL metrics found. Replace any missing cell with: "
                "Not found in retrieved documents\n\n"
                "## Key Differences\n"
                "- ▲ [Metric]: [old value] → [new value], +X% — [one-sentence insight] [N]\n"
                "- ▼ [Metric]: [old value] → [new value], −X% — [one-sentence insight] [N]\n"
                "List increases first, then decreases. Skip metrics with only one side.\n\n"
                "## Sources\n"
                "[N] [Document name], Page [page] (or section if no page number)\n\n"
            )
        elif intent == "list":
            parts.append(
                "RESPONSE FORMAT — TYPE 8: BULLET LIST\n"
                "**[Category]:**\n"
                "• [item from context] [N]\n"
                "• [item from context] [N]\n"
                "List ONLY items explicitly in context. No extras.\n\n"
            )
        elif intent == "table":
            parts.append(
                "RESPONSE FORMAT — TYPE 9: TABLE\n"
                "Build a markdown table with data verbatim from context.\n"
                "Include source citations below the table.\n\n"
            )
        elif intent == "pageref":
            parts.append(
                "RESPONSE FORMAT — TYPE 10: PAGE REFERENCE\n"
                "**Page:** [page number] [N]\n"
                "**Document:** [document name]\n"
                "**Section:** [section heading if available]\n"
                "**Excerpt:** \"[brief verbatim quote from context]\"\n"
                "No Related Questions.\n\n"
            )
        elif intent == "analytical":
            parts.append(_MULTI_HOP_DIRECTIVE)
        elif intent == "chart":
            parts.append(
                "RESPONSE FORMAT — TYPE 12: CHART\n"
                "If numerical series data exists in context, emit a chart block.\n"
                "Otherwise offer the data as a table instead.\n\n"
            )
        elif intent == "process":
            parts.append(
                "RESPONSE FORMAT — STEP-BY-STEP PROCESS\n"
                "**Steps:**\n"
                "1. [step from context] [N]\n"
                "2. [step from context] [N]\n"
                "Each step must come directly from context.\n\n"
            )
        elif intent == "financial":
            parts.append(
                "RESPONSE FORMAT — TYPE 3 (FINANCIAL DATA)\n"
                "Format each metric: **[Metric]:** [Exact value] [N]\n"
                "Do NOT start with 'According to...' or 'The document states...'.\n"
                "Never round, estimate, or paraphrase numbers.\n\n"
            )
        elif intent == "arithmetic":
            parts.append(
                "RESPONSE FORMAT — MULTI-HOP ARITHMETIC\n\n"
                "The answer requires combining values from multiple excerpts.\n\n"
                "━━━ RULES ━━━\n"
                "1. Collect EVERY numeric component from the retrieved excerpts.\n"
                "2. Show each component value with its [N] source citation.\n"
                "3. Show the arithmetic step-by-step:\n"
                "   value1 [N] + value2 [N] = result\n"
                "4. State the final answer in **bold**.\n"
                "5. Never invent or estimate — every number must be cited.\n\n"
                "━━━ OUTPUT FORMAT ━━━\n\n"
                "**Final Answer:** [bold result]\n\n"
                "**Reasoning:**\n"
                "[Component]: [value] [N] + [Component]: [value] [N] = [result]\n\n"
                "**Supporting Evidence:**\n"
                "- [Component]: [value] [N]\n"
                "- [Component]: [value] [N]\n\n"
                "**Sources:**\n"
                "[N] [Document Name], Page [page number]\n\n"
                "**Confidence:** High | Medium | Low\n\n"
            )
        elif intent == "compliance":
            parts.append(
                "RESPONSE FORMAT — COMPLIANCE EVALUATION\n\n"
                "You are an enterprise compliance assistant. Evaluate the user's "
                "scenario against EVERY applicable policy in the retrieved excerpts.\n\n"
                "EXHAUSTIVENESS RULES (most important):\n"
                "1. The scenario may contain MULTIPLE facts that each map to a different "
                "policy (e.g. remote work + password length + reimbursement deadline). "
                "You MUST evaluate each fact independently against its applicable policy. "
                "NEVER stop after finding the first violation.\n"
                "2. Before writing the answer, enumerate every scenario fact and the "
                "policy it maps to. If a fact has no matching policy in the excerpts, "
                "record it as 'no applicable policy found' — do not silently drop it.\n"
                "3. Boundary values (exactly 30 days, exactly 12 chars) must be evaluated "
                "with the exact inequality in the policy ('within 30 days' = ≤ 30; "
                "'minimum 12 characters' = ≥ 12).\n"
                "4. If two retrieved excerpts give conflicting rules (e.g. claim within 30 "
                "days vs claim within 45 days), report this as a CONTRADICTION rather than "
                "picking one silently. Cite both sources.\n\n"
                "CITATION RULES:\n"
                "5. Every rule statement and every scenario fact taken from documents must "
                "carry an inline [N] citation. Use the section heading from the chunk "
                "header when available (e.g. 'Travel Policy → Claims within 30 Days [3]').\n"
                "6. The Sources section must list one line per cited [N], including the "
                "document name, section heading (if known), and page number.\n\n"
                "REASONED INFERENCE RULES:\n"
                "7. If the user asks for prioritization, risk ranking, or 'which is most "
                "important' and the documents do not state an explicit order, you MAY "
                "provide a reasoned assessment based on standard security/business "
                "principles. You MUST clearly label this section as:\n"
                "   **Reasoned Inference (not stated in documents):**\n"
                "   …so the user knows it is not a direct citation.\n"
                "8. Never use inference to fabricate a policy rule or threshold — "
                "inference is only allowed for prioritization/risk assessment when the "
                "documents are silent on ordering.\n\n"
                "OUTPUT FORMAT — keep it clean and user-facing. Use these exact "
                "section headers in this order. OMIT any section that does not apply "
                "(e.g. no Compliant Items, no Contradictions). Never include empty sections.\n\n"
                "**Compliance Result:** PASS | FAIL | PARTIAL | INSUFFICIENT EVIDENCE\n\n"
                "**Violations:**\n"
                "- [Short violation name — one short clause] [N]\n"
                "- …\n"
                "(One bullet per violation. Omit this section entirely if none.)\n\n"
                "**Compliant Items:**\n"
                "- [Short item name] [N]\n"
                "(Omit this section entirely if none.)\n\n"
                "**Risk Level:** High | Medium | Low\n\n"
                "**Contradictions:** (include ONLY when excerpts conflict)\n"
                "- Source A: [excerpt + citation]\n"
                "- Source B: [excerpt + citation]\n\n"
                "**Reasoned Inference:** (include ONLY when applicable per rule 7; "
                "prefix with 'This conclusion is based on the information available "
                "in the documents.')\n"
                "[One short paragraph.]\n\n"
                "**Source:**\n"
                "[Document Name] | Page [page number] | [Section heading when known]\n"
                "(One line per cited [N].)\n\n"
                "**Confidence:** High | Medium | Low\n\n"
                "FORBIDDEN: never include Supporting Evidence bullet lists, "
                "retrieval diagnostics, chunk counts, similarity scores, "
                "'What was searched', or 'Suggestions' inside a compliance answer.\n\n"
            )
        elif intent == "ranking":
            parts.append(
                "RESPONSE FORMAT — RANKING\n\n"
                "The answer requires extracting ALL candidate values and sorting them.\n\n"
                "━━━ RULES ━━━\n"
                "1. Extract the relevant metric for EVERY candidate from the retrieved excerpts.\n"
                "2. Assign each value to its named item (plan, product, year, etc.).\n"
                "3. Sort the values correctly per the question (highest→lowest or lowest→highest).\n"
                "4. If a candidate's value is missing, list it as N/A — never omit it.\n"
                "5. Never invent or estimate any value — every number must be cited.\n\n"
                "━━━ OUTPUT FORMAT ━━━\n\n"
                "**Final Answer:** [Item with highest/lowest metric] [N]\n\n"
                "**Reasoning:**\n"
                "All candidates extracted and sorted:\n\n"
                "**Ranked [Metric] ([highest first / lowest first]):**\n"
                "1. [Item A]: [Value] [N]\n"
                "2. [Item B]: [Value] [N]\n"
                "3. [Item C]: [Value] [N]\n\n"
                "**Supporting Evidence:**\n"
                "- [Fact] [N]\n\n"
                "**Sources:**\n"
                "[N] [Document Name], Page [page number]\n\n"
                "**Confidence:** High | Medium | Low\n\n"
            )
        elif complexity == "definition":
            parts.append(
                "LENGTH DIRECTIVE: Definition question. "
                "State what it is in 1–2 sentences, then cite [N]. Nothing else.\n\n"
            )
        elif complexity == "short":
            parts.append(
                "LENGTH DIRECTIVE: Short question. "
                "1–3 sentences maximum. No headers. No bullet lists.\n\n"
            )
        elif complexity == "detailed":
            parts.append(_MULTI_HOP_DIRECTIVE)
        else:
            parts.append(
                "RESPONSE FORMAT — CLEAN USER-FACING ANSWER\n\n"
                "Synthesize from ALL relevant excerpts; combine across documents and "
                "sections; perform calculations, date arithmetic, comparisons, and "
                "policy interpretation when the question requires them. Never return "
                "raw chunk text. Never include retrieval diagnostics.\n\n"
                "━━━ OUTPUT FORMAT (use these exact section headers; OMIT any section "
                "that does not apply — never include an empty section) ━━━\n\n"
                "**Answer:**\n"
                "[Direct conclusion. Lead with the answer. Inline [N] on factual claims.]\n\n"
                "**Reason:** (include ONLY for reasoning, comparison, calculation, "
                "date, or compliance questions; OMIT for direct single-fact lookups)\n"
                "[One short paragraph: the rule, threshold, calculation, or evidence "
                "chain that produced the answer.]\n\n"
                "**Source:**\n"
                "[Document Name] | Page [page number] | [Section heading when known]\n"
                "(One line per cited [N]. Merge duplicates.)\n\n"
                "**Confidence:** High | Medium | Low\n\n"
                "FORBIDDEN — never output any of the following in the user-facing answer:\n"
                "• 'Supporting Evidence' bullet lists (the Source line is sufficient).\n"
                "• 'What was searched' / 'What was looked for' sections.\n"
                "• Retrieved chunk counts, relevance percentages, similarity scores.\n"
                "• 'Suggestions' — only the not-found fallback layer adds those.\n"
                "• Any reference to internal chunk IDs, embeddings, or retrieval metadata.\n\n"
                "INFERENCE, MISSING INFO, CONFLICTS:\n"
                "• If the answer requires inference, append after the Answer:\n"
                "   *This conclusion is based on the information available in the documents.*\n"
                "• If the documents lack enough information, the Answer must say: "
                "'The uploaded documents do not contain enough information to answer "
                "this question.' Under Reason, state exactly which fact, policy, value, "
                "or section is missing. Confidence = Low.\n"
                "• If two excerpts conflict, the Answer must say 'Conflicting policies "
                "detected' and Reason must list both sources with their citations and "
                "explain the discrepancy — do not silently pick one.\n\n"
            )

    # Scope header
    if scope_type == "folder" and scope_name:
        parts.append(
            f"CONTEXT SCOPE: You are answering questions about documents in the "
            f"folder \"{scope_name}\". All excerpts below are from this folder only.\n\n"
        )
    elif scope_type == "document" and scope_name:
        parts.append(
            f"CONTEXT SCOPE: You are answering questions about the document "
            f"\"{scope_name}\". All excerpts below are from this document only.\n\n"
        )
    elif scope_type == "domain" and scope_name:
        parts.append(
            f"CONTEXT SCOPE: You are answering questions from the \"{scope_name}\" "
            f"knowledge domain. All excerpts below are from documents in this domain. "
            f"Synthesize a single comprehensive answer from all provided excerpts — "
            f"do not limit yourself to any one document.\n\n"
        )

    # Mode instruction (empty string for "auto")
    mode_instr = MODE_INSTRUCTIONS.get(mode, "")
    if mode_instr:
        parts.append(mode_instr)

    parts.append(SYSTEM_PROMPT)
    return "".join(parts)


def _scoped_no_results_msg(scope_type: str, scope_name: str | None) -> str:
    if scope_type == "folder" and scope_name:
        return f"I could not find a specific answer in the **{scope_name}** folder's documents."
    if scope_type == "document" and scope_name:
        return f"I could not find a specific answer in **{scope_name}**."
    if scope_type == "domain" and scope_name:
        return f"I could not find a specific answer in the **{scope_name}** domain documents."
    return NO_RELEVANT_MSG


# ─────────────────────────────────────────────────────────────────────────────
# Document disambiguation
# ─────────────────────────────────────────────────────────────────────────────

_SEARCH_ALL_PHRASES = frozenset({
    "search all", "all documents", "across all", "all files",
    "every document", "all my documents", "everywhere", "all docs",
    "search everything", "all uploaded",
})


def _wants_all_docs(question: str) -> bool:
    q_lower = question.lower()
    return any(phrase in q_lower for phrase in _SEARCH_ALL_PHRASES)


def _should_disambiguate(
    chunks_with_scores: list[tuple],
    scope_type: str,
    question: str,
) -> list[dict] | None:
    """
    Return a list of domain dicts if the question matches multiple knowledge
    domains with similar relevance — None if no disambiguation is needed.

    Each dict: {domain_name, similarity, document_count}

    Triggers when:
    - scope_type is "all" (not already scoped to folder / document / domain)
    - User hasn't asked to search all documents
    - 2+ domains have high similarity scores
    - Gap between top-2 domain scores < 15 % of top score
    - Top similarity >= 0.50 (question is genuinely relevant)

    Documents without a domain_name are each treated as their own pseudo-domain
    so they still appear in the picker rather than silently collapsing.
    """
    if scope_type != "all":
        return None
    if _wants_all_docs(question):
        return None
    if not chunks_with_scores:
        return None

    # Best similarity + distinct doc IDs per domain key
    domain_best: dict[str, tuple[str, float]] = {}   # key → (display_name, best_sim)
    domain_docs: dict[str, set[str]]           = {}   # key → set of doc_ids

    for _chunk, doc, dist in chunks_with_scores:
        sim = round(1.0 - float(dist), 4)
        # Use domain_name when set; fall back to doc UUID so unclassified docs are
        # each their own "domain" rather than merging into a nameless bucket.
        domain_key   = doc.domain_name if doc.domain_name else str(doc.id)
        display_name = doc.domain_name if doc.domain_name else doc.original_name
        doc_id_str   = str(doc.id)

        if domain_key not in domain_best or sim > domain_best[domain_key][1]:
            domain_best[domain_key] = (display_name, sim)
        domain_docs.setdefault(domain_key, set()).add(doc_id_str)

    if len(domain_best) < 2:
        return None

    ranked = sorted(domain_best.items(), key=lambda x: x[1][1], reverse=True)
    top_sim    = ranked[0][1][1]
    second_sim = ranked[1][1][1]

    if top_sim < 0.50:
        return None

    gap = top_sim - second_sim
    if gap >= top_sim * 0.15:
        return None  # clear winner domain — answer directly

    threshold = top_sim * 0.85
    candidates = [
        {
            "domain_name":    display_name,
            "similarity":     round(sim, 3),
            "document_count": len(domain_docs.get(key, set())),
        }
        for key, (display_name, sim) in ranked
        if sim >= threshold
    ]

    return candidates if len(candidates) >= 2 else None


# ─────────────────────────────────────────────────────────────────────────────
# Core helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _count_eligible_chunks(
    user_id: uuid.UUID,
    db: AsyncSession,
    scope_type: str = "all",
    scope_id: uuid.UUID | None = None,
    scope_name: str | None = None,
) -> dict:
    """
    Run fast COUNT queries at every filter stage so you can see exactly
    how many chunks survive each WHERE clause before the vector search runs.

    Returns a dict with counts at each layer:
      total_chunks         – every chunk in document_chunks
      owned_by_user        – after Document.user_id = user_id
      in_indexed_docs      – after Document.status = 'indexed'
      with_embedding       – after embedding IS NOT NULL
      after_scope          – after folder/document/domain filter
      blocked_by_scope     – with_embedding minus after_scope
    """
    _div = "─" * 72

    # ── Layer 0: total chunks in the system ───────────────────────────────
    total = (await db.scalar(select(func.count(DocumentChunk.id)))) or 0

    # ── Layer 1: user ownership filter ───────────────────────────────────
    owned = (await db.scalar(
        select(func.count(DocumentChunk.id))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
    )) or 0

    # ── Layer 2: document status = 'indexed' ──────────────────────────────
    indexed = (await db.scalar(
        select(func.count(DocumentChunk.id))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
    )) or 0

    # ── Layer 3: embedding IS NOT NULL ────────────────────────────────────
    with_emb = (await db.scalar(
        select(func.count(DocumentChunk.id))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
        .where(DocumentChunk.embedding.is_not(None))
    )) or 0

    # ── Layer 4: scope filter ─────────────────────────────────────────────
    scope_stmt = (
        select(func.count(DocumentChunk.id))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
        .where(DocumentChunk.embedding.is_not(None))
    )
    scope_label = "all (no scope filter)"
    if scope_type == "folder" and scope_id:
        scope_stmt  = scope_stmt.where(Document.folder_id == scope_id)
        scope_label = f"folder  id={scope_id}"
    elif scope_type == "document" and scope_id:
        scope_stmt  = scope_stmt.where(Document.id == scope_id)
        scope_label = f"document  id={scope_id}"
    elif scope_type == "domain" and scope_name:
        scope_stmt  = scope_stmt.where(Document.domain_name == scope_name)
        scope_label = f"domain  name={scope_name!r}"

    after_scope = (await db.scalar(scope_stmt)) or 0
    blocked_by_scope = with_emb - after_scope

    # ── Layer 5: indexed doc count + non-indexed doc count ─────────────
    doc_status_rows = (await db.execute(
        select(Document.status, func.count(Document.id).label("n"))
        .where(Document.user_id == user_id)
        .group_by(Document.status)
    )).all()
    doc_by_status = {r.status: r.n for r in doc_status_rows}

    # ── Log everything ─────────────────────────────────────────────────
    logger.info(f"[FILTER] {_div}")
    logger.info("[FILTER] RETRIEVAL FILTER DIAGNOSTIC — chunks surviving each WHERE clause")
    logger.info(f"[FILTER] {_div}")
    logger.info(f"[FILTER] user_id            : {user_id}")
    logger.info(f"[FILTER] scope              : {scope_label}")
    logger.info(f"[FILTER] {_div}")
    logger.info(f"[FILTER] Layer 0  total_chunks_in_db   : {total:>6}")
    logger.info(f"[FILTER] Layer 1  owned_by_user        : {owned:>6}  "
                f"({total - owned} blocked — belong to other users)")
    logger.info(f"[FILTER] Layer 2  in_indexed_docs      : {indexed:>6}  "
                f"({owned - indexed} blocked — document status != 'indexed')")
    logger.info(f"[FILTER] Layer 3  with_embedding       : {with_emb:>6}  "
                f"({indexed - with_emb} blocked — embedding IS NULL)")
    logger.info(f"[FILTER] Layer 4  after_scope_filter   : {after_scope:>6}  "
                f"({blocked_by_scope} blocked — scope filter [{scope_label}])")
    logger.info(f"[FILTER] {_div}")

    # ── Document inventory ─────────────────────────────────────────────
    logger.info(f"[FILTER] Documents by status for this user:")
    for status, count in sorted(doc_by_status.items()):
        flag = " ← chunks available for search" if status == "indexed" else " ← NOT searchable"
        logger.info(f"[FILTER]   {status:<12} : {count}{flag}")

    # ── Diagnosis ──────────────────────────────────────────────────────
    if after_scope == 0 and with_emb > 0:
        logger.warning(
            f"[FILTER] ⚠ SCOPE FILTER REMOVED ALL CHUNKS  "
            f"scope={scope_label}  "
            f"chunks_before_scope={with_emb}  chunks_after=0  "
            "Fix: verify scope_type and scope_id match an existing document/folder."
        )
    elif after_scope == 0 and indexed == 0:
        logger.warning(
            "[FILTER] ⚠ NO INDEXED DOCUMENTS  "
            "Fix: upload a document and wait for indexing to complete."
        )
    elif after_scope == 0 and with_emb == 0:
        logger.warning(
            f"[FILTER] ⚠ ALL EMBEDDINGS ARE NULL  "
            f"indexed_chunks={indexed}  with_embedding=0  "
            "Fix: delete chunks and re-index documents."
        )
    elif after_scope < 5:
        logger.warning(
            f"[FILTER] ⚠ VERY FEW CHUNKS ELIGIBLE ({after_scope})  "
            "Low recall expected."
        )
    else:
        logger.info(
            f"[FILTER] ✓ {after_scope} chunks eligible for vector search"
        )

    logger.info(f"[FILTER] {_div}")

    return {
        "total":            total,
        "owned_by_user":    owned,
        "in_indexed_docs":  indexed,
        "with_embedding":   with_emb,
        "after_scope":      after_scope,
        "blocked_by_scope": blocked_by_scope,
        "doc_by_status":    doc_by_status,
        "scope_label":      scope_label,
    }


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine distance (0 = identical, 1 = orthogonal)."""
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


_STOP_WORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'of', 'in', 'to', 'for',
    'on', 'at', 'by', 'with', 'from', 'and', 'or', 'but', 'not', 'what',
    'how', 'when', 'where', 'who', 'which', 'this', 'that', 'it', 'its',
    'me', 'my', 'i', 'your', 'their', 'about', 'any', 'all',
})


# Primary trigger terms — the six metrics that always activate financial retrieval
_FINANCIAL_TRIGGER_TERMS = frozenset({
    'revenue', 'operating income', 'gross margin',
    'net income', 'cash flow', 'eps',
    # common abbreviations / alternate phrasings
    'earnings per share', 'free cash flow', 'fcf', 'ebit', 'ebitda',
})

_FINANCIAL_QUERY_TERMS = frozenset({
    'revenue', 'revenues', 'profit', 'profits', 'income', 'earnings',
    'growth', 'margin', 'sales', 'ebitda', 'eps', 'cash flow',
    'net income', 'operating income', 'gross profit', 'gross margin',
    'total revenue', 'net revenue', 'quarterly', 'fiscal', 'financial',
    'segment', 'cost', 'expense', 'loss', 'liabilities', 'assets',
    'cash', 'dividend', 'yield', 'return', 'roe', 'roa', 'roce',
    'capex', 'depreciation', 'amortization', 'working capital',
}) | _FINANCIAL_TRIGGER_TERMS

_FINANCIAL_SECTION_MARKERS = (
    'income', 'revenue', 'financial', 'statement', 'balance',
    'earnings', 'profit', 'loss', 'operations', 'cash flow',
    'highlights', 'results', 'performance',
)

# Fiscal period labels — boost chunks that carry an explicit period label
_FISCAL_PERIOD_LABELS = frozenset({
    'fy2020', 'fy2021', 'fy2022', 'fy2023', 'fy2024', 'fy2025', 'fy2026',
    'fy 2020', 'fy 2021', 'fy 2022', 'fy 2023', 'fy 2024', 'fy 2025',
    'fiscal 2022', 'fiscal 2023', 'fiscal 2024', 'fiscal 2025',
    'fiscal year 2022', 'fiscal year 2023', 'fiscal year 2024', 'fiscal year 2025',
    'q1 fy', 'q2 fy', 'q3 fy', 'q4 fy',
    'first quarter', 'second quarter', 'third quarter', 'fourth quarter',
    'full year', 'annual', 'year ended', 'twelve months ended',
})

# Currency / magnitude tokens — presence signals numeric financial content
_CURRENCY_TOKENS = frozenset({'$', '€', '£', '¥', 'usd', 'eur', 'gbp'})
_MAGNITUDE_TOKENS = frozenset({'million', 'billion', 'trillion', 'mn', 'bn', 'trn'})

# Regex for detecting table rows (markdown pipe tables) with a digit in the row
_TABLE_ROW_RE = _re.compile(r'^\|[^\n]*\d[^\n]*\|', _re.MULTILINE)
# Regex for counting distinct numeric values in a chunk
_NUMERIC_RE = _re.compile(
    r'(?:[\$€£¥]\s*)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
    r'(?:\s*(?:billion|million|trillion|bn|mn|B|M|%))?',
    _re.IGNORECASE,
)


_POLICY_EXCLUDE_TERMS = frozenset({
    'policy', 'policies', 'guideline', 'guidelines', 'procedure', 'procedures',
    'rule', 'rules', 'regulation', 'regulations', 'reimbursement', 'allowance',
    'compliance', 'handbook', 'manual', 'protocol', 'code of conduct',
})


def _is_financial_query(question: str) -> bool:
    """Return True when the question is genuinely about financial statements.

    Policy questions that happen to mention financial words (expense policy,
    salary guideline, travel allowance) are excluded — they should be answered
    from policy documents, not from numeric financial report chunks.
    """
    q = question.lower()
    if any(kw in q for kw in _POLICY_EXCLUDE_TERMS):
        return False
    return any(t in q for t in _FINANCIAL_TRIGGER_TERMS) or \
           any(kw in q for kw in _FINANCIAL_QUERY_TERMS)


def _financial_boost(rows: list[tuple], question: str) -> list[tuple]:
    """
    Multi-signal pre-cross-encoder boost for financial queries.

    Runs AFTER bi-encoder rerank and BEFORE cross-encoder so the top-50
    candidate pool fed to the cross-encoder contains the best financial chunks.

    Scoring signals (additive, then combined with semantic similarity):
    +5  Table chunk        : markdown pipe table rows containing a number
    +4  Financial heading  : chunk starts with [Financial Section] marker
    +3  High numeric density: 4+ numeric values in content
    +1  Moderate numeric   : 2–3 numeric values
    +2  Per metric keyword : query metric term found in chunk (revenue, EPS, …)
    +2  Period match       : query's fiscal year/quarter appears in chunk
    +1  Period present     : any fiscal period label found in chunk
    +1  Currency token     : $, €, £, billion, million found in chunk

    Final score = 0.55 × semantic_similarity + 0.45 × (normalised signal score)
    Chunks are sorted by final score descending.
    """
    if not rows:
        return rows

    q_lower = question.lower()
    if not _is_financial_query(question):
        return rows

    # Extract the specific metric keywords from this query
    q_words = {w.lower().strip('?.,!;:\'\"') for w in question.split() if len(w) > 2}
    metric_q_words = q_words & _FINANCIAL_QUERY_TERMS

    # Which fiscal periods does the question explicitly reference?
    q_period_refs = {lbl for lbl in _FISCAL_PERIOD_LABELS if lbl in q_lower}

    def _signal_score(chunk_content: str) -> float:
        cl = chunk_content.lower()
        s  = 0.0

        # Table rows with numbers
        if _TABLE_ROW_RE.search(chunk_content):
            s += 5

        # Financial section heading
        if chunk_content.lstrip().startswith('[') and \
                any(m in cl[:120] for m in _FINANCIAL_SECTION_MARKERS):
            s += 4

        # Numeric density
        n_nums = len(_NUMERIC_RE.findall(chunk_content))
        if n_nums >= 4:
            s += 3
        elif n_nums >= 2:
            s += 1

        # Per metric keyword from query
        s += sum(2 for kw in metric_q_words if kw in cl)

        # Fiscal period: extra for the query's exact year, base for any period
        if q_period_refs:
            s += sum(2 for lbl in q_period_refs if lbl in cl)
        s += min(2, sum(1 for lbl in _FISCAL_PERIOD_LABELS if lbl in cl))

        # Currency / magnitude tokens
        s += sum(0.5 for tok in _CURRENCY_TOKENS  if tok in cl)
        s += sum(0.5 for tok in _MAGNITUDE_TOKENS if tok in cl)

        return s

    # Compute max possible signal score for normalisation (cap at 1.0)
    scored: list[tuple] = []
    raw_signals = []
    for item in rows:
        chunk, _doc, dist = item
        sig = _signal_score(chunk.content or '')
        raw_signals.append(sig)
        scored.append((item, sig))

    max_sig = max(raw_signals) if raw_signals else 1.0
    if max_sig == 0.0:
        max_sig = 1.0

    def _combined(entry: tuple) -> float:
        item, sig = entry
        _, _, dist = item
        sem_sim = max(0.0, min(1.0, 1.0 - float(dist)))
        norm_sig = sig / max_sig
        return -(0.55 * sem_sim + 0.45 * norm_sig)   # negate: sort ascending → best first

    scored.sort(key=_combined)

    logger.info(
        f"[FinBoost] Applied financial boost — "
        f"metric_kw={list(metric_q_words)}  "
        f"period_refs={list(q_period_refs)}  "
        f"chunks={len(rows)}  "
        f"top3_signals={[round(s, 1) for _, s in scored[:3]]}"
    )

    return [item for item, _ in scored]


def _rerank(chunks_with_scores: list[tuple], question: str) -> list[tuple]:
    """Re-rank by combined semantic similarity + keyword coverage.

    Weights vary by query type:
    - Financial queries : 50 % semantic + 50 % keyword coverage
      (exact metric terms matter as much as embedding similarity)
    - All other queries : 65 % semantic + 35 % keyword coverage

    The combined metric is converted back to a distance-like value (lower = better)
    so the rest of the pipeline stays unchanged.
    """
    if not chunks_with_scores:
        return []

    q_words = {
        w.lower().strip('?.,!;:\'\"')
        for w in question.split()
        if len(w) > 2 and w.lower() not in _STOP_WORDS
    }
    if not q_words:
        return chunks_with_scores

    fin_query = _is_financial_query(question)
    sem_w = 0.50 if fin_query else 0.65
    kw_w  = 0.50 if fin_query else 0.35

    reranked: list[tuple] = []
    for chunk, doc, dist in chunks_with_scores:
        semantic_sim  = max(0.0, min(1.0, 1.0 - float(dist)))
        content_lower = (chunk.content or '').lower()
        matched       = sum(1 for kw in q_words if kw in content_lower)
        kw_coverage   = matched / len(q_words)
        combined_sim  = sem_w * semantic_sim + kw_w * kw_coverage
        reranked.append((chunk, doc, 1.0 - combined_sim))

    reranked.sort(key=lambda x: x[2])
    return reranked


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval Validation Layer
# Runs post-reranking to detect cross-domain contamination and enforce
# intent–content alignment before chunks are sent to the LLM.
# ─────────────────────────────────────────────────────────────────────────────

def _get_chunk_section(chunk) -> str:
    """Extract section heading from a chunk — column or [HEADING] content prefix."""
    heading = getattr(chunk, 'section_heading', None) or ''
    if heading:
        return heading.strip()
    content = chunk.content or ''
    if content.startswith('['):
        end = content.find(']')
        if 0 < end < 200:
            return content[1:end].strip()
    return ''


_HR_ONBOARDING_SECTIONS = frozenset({
    'onboarding', 'orientation', 'new hire', 'welcome to', 'joining',
    'first day', 'induction', 'employee handbook',
})
_FINANCIAL_STMT_SECTIONS = frozenset({
    'consolidated statements', 'income statement', 'balance sheet',
    'cash flow statement', 'financial highlights', 'notes to financial',
    'earnings per share', 'segment revenue',
})
_EXPENSE_POLICY_SECTIONS = frozenset({
    'expense policy', 'travel policy', 'reimbursement', 'expense claim',
    'travel and expense', 'expense report', 'travel reimbursement',
})


def _validate_retrieval(
    chunks: list[tuple],
    question: str,
    intent: str,
) -> tuple[list[tuple], list[str]]:
    """
    Post-reranking retrieval validation.

    Detects cross-domain contamination and enforces basic intent–content
    alignment.  Filters clearly mismatched chunks but always preserves at
    least RERANKER_MIN_RESULTS chunks to prevent empty responses.

    Returns (possibly_filtered_chunks, issue_descriptions).
    """
    if not chunks:
        return chunks, []

    issues: list[str] = []
    q_lower = question.lower()

    is_expense_q = any(t in q_lower for t in (
        'expense policy', 'travel reimbursement', 'travel allowance',
        'travel policy', 'reimbursement policy', 'expense claim',
        'expense report', 'mileage', 'per diem',
    ))
    is_vendor_q = any(t in q_lower for t in (
        'vendor onboarding', 'contractor onboarding', 'vendor policy',
        'vendor process', 'supplier onboarding',
    ))
    is_financial_metric_q = (
        intent in ('numerical', 'financial')
        and not any(t in q_lower for t in ('policy', 'guideline', 'procedure', 'expense'))
    )

    filtered: list[tuple] = []
    for chunk, doc, dist in chunks:
        section = _get_chunk_section(chunk).lower()
        remove = False
        reason = ''

        if is_expense_q and section:
            if any(s in section for s in _HR_ONBOARDING_SECTIONS):
                remove = True
                reason = (
                    f"cross_domain: expense query matched onboarding section "
                    f"'{section[:60]}' in {doc.original_name!r}"
                )
            elif any(s in section for s in _FINANCIAL_STMT_SECTIONS):
                remove = True
                reason = (
                    f"cross_domain: expense query matched financial-statement section "
                    f"'{section[:60]}' in {doc.original_name!r}"
                )

        if is_financial_metric_q and section:
            if any(s in section for s in _HR_ONBOARDING_SECTIONS):
                remove = True
                reason = (
                    f"cross_domain: financial query matched onboarding section "
                    f"'{section[:60]}' in {doc.original_name!r}"
                )
            elif any(s in section for s in _EXPENSE_POLICY_SECTIONS):
                remove = True
                reason = (
                    f"cross_domain: financial query matched expense-policy section "
                    f"'{section[:60]}' in {doc.original_name!r}"
                )

        if remove:
            issues.append(reason)
            logger.info(f"[Validation] Filtered: {reason}")
        else:
            filtered.append((chunk, doc, dist))

    # Safety guard: never filter below RERANKER_MIN_RESULTS
    if filtered and len(filtered) < settings.RERANKER_MIN_RESULTS:
        logger.info(
            f"[Validation] Filtering would leave {len(filtered)} chunks "
            f"(min={settings.RERANKER_MIN_RESULTS}) — restoring original set"
        )
        issues.append(
            f"filter_restored: cross-domain filter too aggressive "
            f"({len(filtered)} < {settings.RERANKER_MIN_RESULTS}) — original set kept"
        )
        return chunks, issues

    return (filtered if filtered else chunks), issues


# ─────────────────────────────────────────────────────────────────────────────
# P4 — Section metadata boost
# Maps a detected query domain → section heading keywords used to boost chunks
# whose section_heading contains those words in the cosine candidate pool.
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_HINT_WORDS: dict[str, list[str]] = {
    'travel':     ['travel', 'trip', 'flight', 'hotel', 'accommodation', 'mileage', 'per diem'],
    'expense':    ['expense', 'reimbursement', 'claim', 'receipt', 'spend'],
    'leave':      ['pto', 'vacation', 'leave', 'time off', 'sick', 'holiday', 'absence', 'annual'],
    'onboarding': ['onboarding', 'joining', 'new hire', 'orientation', 'first day', 'induction'],
    'product':    ['product', 'plan', 'tier', 'pricing', 'enterprise', 'professional',
                   'storage', 'api', 'feature', 'subscription', 'package'],
    'policy':     ['policy', 'procedure', 'guideline', 'rule', 'compliance', 'standard'],
    'financial':  ['income', 'revenue', 'financial', 'balance', 'earnings', 'cash flow',
                   'profit', 'loss', 'highlights', 'results', 'performance'],
    'leadership': ['executive', 'leadership', 'management', 'board', 'officer', 'director'],
}


def _extract_section_hint(question: str) -> str | None:
    """Return the primary section domain for the query, or None."""
    q = question.lower()
    for domain, keywords in _SECTION_HINT_WORDS.items():
        if any(kw in q for kw in keywords):
            return domain
    return None


# ─────────────────────────────────────────────────────────────────────────────
# P6 — Parent-child context expansion
# After the reranker, fetch sibling chunks from the same section so the LLM
# receives the full section context around every matched chunk.
# Example: a matched "API limit: 500,000" row also returns the surrounding
# "NexaCloud Enterprise" product card paragraphs.
# ─────────────────────────────────────────────────────────────────────────────

def _metadata_filter_rows(
    rows: list[tuple],
    question: str,
    *,
    min_results: int | None = None,
) -> tuple[list[tuple], dict[str, object]]:
    """Prefer chunks whose stored metadata category matches the query domain.

    This is fallback-safe: if metadata is absent or too few rows match, the
    original rows are returned.
    """
    allowed_categories = infer_query_categories(question)
    if not rows or not allowed_categories:
        return rows, {
            "enabled": False,
            "allowed_categories": sorted(allowed_categories),
            "matched": 0,
            "original": len(rows),
        }

    matched = [row for row in rows if row_matches_categories(row, allowed_categories)]
    required = min_results if min_results is not None else settings.MIN_RETRIEVAL_RESULTS

    if len(matched) >= required:
        return matched, {
            "enabled": True,
            "allowed_categories": sorted(allowed_categories),
            "matched": len(matched),
            "original": len(rows),
        }

    return rows, {
        "enabled": False,
        "allowed_categories": sorted(allowed_categories),
        "matched": len(matched),
        "original": len(rows),
    }

async def _expand_section_context(
    rows: list[tuple],
    db: AsyncSession,
) -> list[tuple]:
    """Fetch adjacent section-sibling chunks for every matched chunk that has a
    section_heading.  Siblings are added with a synthetic distance of 0.32 so
    they appear after the directly-matched chunks but still within the context
    block sent to the LLM.

    Respects PARENT_CHILD_MAX_SIBLINGS (max extra chunks per matched section)
    and PARENT_CHILD_LLM_CAP (total chunks after expansion).
    """
    if not rows or not settings.PARENT_CHILD_EXPANSION_ENABLED:
        return rows

    max_siblings = settings.PARENT_CHILD_MAX_SIBLINGS
    llm_cap      = settings.PARENT_CHILD_LLM_CAP
    existing_ids: set = {chunk.id for chunk, _, _ in rows}
    extra:        list[tuple] = []

    for chunk, doc, dist in rows[:settings.RERANKER_TOP_K]:
        heading = getattr(chunk, 'section_heading', None)
        if not heading:
            continue
        try:
            sibling_stmt = (
                select(DocumentChunk, Document)
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(DocumentChunk.document_id == chunk.document_id)
                .where(DocumentChunk.section_heading == heading)
                .where(DocumentChunk.chunk_index.between(
                    max(0, chunk.chunk_index - 1),
                    chunk.chunk_index + max_siblings,
                ))
                .order_by(DocumentChunk.chunk_index)
            )
            siblings = (await db.execute(sibling_stmt)).all()
            for sibling, sibling_doc in siblings:
                if sibling.id not in existing_ids and sibling.embedding is not None:
                    existing_ids.add(sibling.id)
                    extra.append((sibling, sibling_doc, 0.32))
        except Exception as _exc:
            logger.warning(f"[ParentChild] Sibling fetch failed: {_exc}")

    if extra:
        logger.info(
            f"[ParentChild] Context expansion: +{len(extra)} sibling chunk(s) "
            f"from {len([r for r in rows[:settings.RERANKER_TOP_K] if getattr(r[0], 'section_heading', None)])} "
            f"section(s)  cap={llm_cap}"
        )

    combined = rows + extra
    combined.sort(key=lambda x: x[2])
    return combined[:llm_cap]


def _compute_arithmetic_from_chunks(
    question: str,
    rows: list[tuple],
) -> dict | None:
    """
    Best-effort arithmetic extraction for the degraded (no-LLM) path.

    Scans retrieved chunks for numeric values that share the question's
    implied unit (days, hours, weeks, $).  Returns a breakdown dict or
    None when fewer than 2 components are found.

    Return shape: {"total": int|float, "unit": str, "components": [{"value", "context"}…]}
    """
    import re as _re

    q_lower = question.lower()

    # Infer the unit of interest
    unit = ""
    if any(k in q_lower for k in ("day", "days", "leave", "pto", "vacation", "holiday", "absence")):
        unit = "days"
    elif any(k in q_lower for k in ("hour", "hours")):
        unit = "hours"
    elif any(k in q_lower for k in ("week", "weeks")):
        unit = "weeks"
    elif any(k in q_lower for k in ("month", "months")):
        unit = "months"

    # Match a number optionally followed by a unit word
    _num_re = _re.compile(
        r'(\d+(?:\.\d+)?)\s*(?:days?|hours?|weeks?|months?|years?)?',
        _re.IGNORECASE,
    )

    components: list[dict] = []
    seen_values: set[float] = set()

    for chunk, _doc, _dist in rows[:8]:
        content = (chunk.content or "").strip()
        c_lower = content.lower()

        # Only scan chunks that mention the unit
        if unit and unit.rstrip("s") not in c_lower:
            continue

        for sent in _re.split(r'[.!?\n]', content):
            sent = sent.strip()
            if not sent or (unit and unit.rstrip("s") not in sent.lower()):
                continue
            for m in _num_re.finditer(sent):
                val = float(m.group(1))
                if val <= 0 or val > 365 or val in seen_values:
                    continue
                seen_values.add(val)
                components.append({
                    "value":   val,
                    "context": sent[:120].strip(),
                })
                if len(components) >= 6:
                    break
            if len(components) >= 6:
                break

    if len(components) < 2:
        return None

    total = sum(c["value"] for c in components)
    total = round(total, 2)
    if total == int(total):
        total = int(total)

    return {"total": total, "unit": unit, "components": components}


def _error_type_to_message(error_type: str | None, provider: str | None = None) -> str:
    """Convert an AIServiceUnavailableError error_type to a user-readable sentence."""
    pname = provider or "AI provider"
    if error_type == "auth_failed":
        return f"{pname} API key is invalid or revoked — check your .env file."
    if error_type == "quota_exceeded":
        return f"{pname} daily quota has been exceeded — answer generated from document excerpts."
    if error_type == "not_configured":
        # Generic message — never leak env-var names or backend file paths to end users.
        # Operators see the full reason in server logs and via /health/providers.
        return "AI answer synthesis is temporarily unavailable. Please try again shortly."
    if error_type == "unavailable":
        return f"{pname} is temporarily unavailable (timeout or service outage)."
    return f"{pname} is temporarily unavailable."


def _local_answer_from_chunks(
    question: str,
    rows: list[tuple],
    error_reason: str | None = None,
) -> str:
    """
    Local fallback used when all AI providers fail.

    By default (DEBUG_MODE=false) returns a clean failure message so the user
    is never shown raw retrieval content. Source citations are still emitted
    by the caller via the sources SSE event so the document trail is intact.

    When DEBUG_MODE=true, falls through to the legacy excerpt view so
    operators can see what retrieval produced even when generation failed.
    """
    import re as _re

    if not rows:
        return NO_RELEVANT_MSG

    if not settings.DEBUG_MODE:
        _suffix = f" ({error_reason})" if error_reason else ""
        return (
            "**Unable to generate an answer at the moment. Please try again.**"
            f"{_suffix}\n\n"
            "If the problem persists, check `GET /api/v1/debug/provider-health` "
            "for per-provider status."
        )

    intent = _intent_classify(question)

    q_words = {
        w.lower().strip('?.,!;:\'\"')
        for w in question.split()
        if len(w) > 2 and w.lower() not in _STOP_WORDS
    }

    all_chunks: list[tuple] = []  # (ref, content, doc_name, page_str)
    for i, (chunk, doc, _dist) in enumerate(rows[:10], 1):
        content  = (chunk.content or '').strip()
        doc_name = doc.original_name
        page     = str(chunk.page_number) if chunk.page_number else None
        all_chunks.append((i, content, doc_name, page))

    def _score(sent: str) -> float:
        sl = sent.lower()
        matched = sum(1 for kw in q_words if kw in sl)
        return matched / max(len(q_words), 1)

    def _sentences(content: str, n: int = 3) -> list[str]:
        parts = _re.split(r'(?<=[.!?])\s+', content)
        parts = [s.strip() for s in parts if len(s.strip()) > 20]
        if not parts:
            return [content[:300]]
        return sorted(parts, key=_score, reverse=True)[:n] if len(parts) > n else parts

    def _src(ref: int, doc_name: str, page: str | None) -> str:
        return f"[{ref}] {doc_name}" + (f", p.{page}" if page else "")

    num_re = _re.compile(
        r'[\$€£¥]?[\d,]+(?:\.\d+)?'
        r'(?:\s*(?:million|billion|trillion|thousand|%|percent))?',
        _re.IGNORECASE,
    )

    lines:        list[str] = []
    source_notes: list[str] = []

    if intent in ('oneword', 'shortfact'):
        ref, content, doc_name, page = all_chunks[0]
        best = _sentences(content, 1)
        lines.append("✓ " + (best[0] + f" [{ref}]" if best else content[:200] + f" [{ref}]"))
        source_notes.append(_src(ref, doc_name, page))

    elif intent in ('numerical', 'financial'):
        for ref, content, doc_name, page in all_chunks[:5]:
            for sent in _sentences(content, 3):
                if num_re.search(sent):
                    lines.append(f"✓ {sent} [{ref}]")
            source_notes.append(_src(ref, doc_name, page))
        if not lines:
            for ref, content, doc_name, page in all_chunks[:3]:
                for s in _sentences(content, 2):
                    lines.append(f"✓ {s} [{ref}]")
                source_notes.append(_src(ref, doc_name, page))

    elif intent == 'arithmetic':
        # Show numeric facts + compute likely answer
        for ref, content, doc_name, page in all_chunks[:8]:
            for sent in _sentences(content, 3):
                if num_re.search(sent):
                    lines.append(f"✓ {sent} [{ref}]")
            source_notes.append(_src(ref, doc_name, page))
        arith = _compute_arithmetic_from_chunks(question, rows)
        if arith and len(arith["components"]) >= 2:
            total = arith["total"]
            unit  = arith["unit"]
            parts_str = " + ".join(
                str(int(c["value"]) if c["value"] == int(c["value"]) else c["value"])
                for c in arith["components"]
            )
            lines.append(f"\n*Likely answer: **{total} {unit}** ({parts_str} = {total})*")

    elif intent == 'definition':
        ref, content, doc_name, page = all_chunks[0]
        for s in _sentences(content, 3):
            lines.append(f"✓ {s} [{ref}]")
        source_notes.append(_src(ref, doc_name, page))

    elif intent == 'explanation':
        for ref, content, doc_name, page in all_chunks[:4]:
            for s in _sentences(content, 2):
                lines.append(f"✓ {s} [{ref}]")
            source_notes.append(_src(ref, doc_name, page))

    elif intent == 'summary':
        n_pt = 1
        for ref, content, doc_name, page in all_chunks[:6]:
            for s in _sentences(content, 2):
                lines.append(f"{n_pt}. {s} [{ref}]")
                n_pt += 1
                if n_pt > 7:
                    break
            source_notes.append(_src(ref, doc_name, page))
            if n_pt > 7:
                break

    elif intent == 'comparison':
        lines.append("**Retrieved values:**\n")
        for ref, content, doc_name, page in all_chunks[:8]:
            for sent in _sentences(content, 3):
                if num_re.search(sent):
                    lines.append(f"✓ {sent} [{ref}]")
            source_notes.append(_src(ref, doc_name, page))

    elif intent == 'list':
        for ref, content, doc_name, page in all_chunks[:5]:
            for s in _sentences(content, 3):
                lines.append(f"✓ {s} [{ref}]")
            source_notes.append(_src(ref, doc_name, page))

    elif intent == 'process':
        n_step = 1
        for ref, content, doc_name, page in all_chunks[:5]:
            for s in _sentences(content, 3):
                lines.append(f"{n_step}. {s} [{ref}]")
                n_step += 1
            source_notes.append(_src(ref, doc_name, page))

    elif intent == 'pageref':
        ref, content, doc_name, page = all_chunks[0]
        lines.append(f"**Page:** {page or 'N/A'} [{ref}]")
        lines.append(f"**Document:** {doc_name}")
        excerpt = _sentences(content, 1)
        if excerpt:
            lines.append(f"**Excerpt:** \"{excerpt[0]}\"")
        source_notes.append(_src(ref, doc_name, page))

    else:  # general / analytical / table / chart
        for ref, content, doc_name, page in all_chunks[:5]:
            for s in _sentences(content, 3):
                lines.append(f"✓ {s} [{ref}]")
            source_notes.append(_src(ref, doc_name, page))

    if not lines:
        return NO_RELEVANT_MSG

    seen_notes: set[str] = set()
    unique_notes = [n for n in source_notes if not (n in seen_notes or seen_notes.add(n))]  # type: ignore[func-returns-value]

    _reason_suffix = f" {error_reason}" if error_reason else ""
    _footer_detail = f" ({error_reason})" if error_reason else ""
    return (
        f"**Answer generation is temporarily unavailable.**{_reason_suffix}\n\n"
        "Based on your uploaded documents:\n\n"
        + '\n'.join(lines)
        + "\n\n**Sources:**\n" + '\n'.join(unique_notes)
        + f"\n\n> ℹ *AI synthesis unavailable{_footer_detail} — "
          "showing the most relevant excerpts from your documents.*"
    )


def _build_direct_excerpt(rows: list[tuple], error_reason: str | None = None) -> str:
    """Return up to 3 numbered document excerpts with source labels.

    Lightweight fallback used when the AI provider is unavailable.
    Content is truncated to 500 chars per excerpt to keep the response
    readable.  Returns NO_RELEVANT_MSG when rows is empty.
    """
    if not rows:
        return NO_RELEVANT_MSG

    parts: list[str] = []
    for i, (chunk, doc, _dist) in enumerate(rows[:3], 1):
        content  = (chunk.content or '').strip()[:500]
        doc_name = doc.original_name
        page     = str(chunk.page_number) if chunk.page_number else None
        page_str = f", Page {page}" if page else ""
        parts.append(f"**[{i}]** {doc_name}{page_str}\n> {content}")

    body = "\n\n".join(parts)
    _footer_detail = f" ({error_reason})" if error_reason else ""
    return (
        body
        + f"\n\n> ℹ *AI synthesis unavailable{_footer_detail} — "
          "showing the most relevant excerpts found in your documents.*"
    )


def _format_page_aggregation_answer(
    rows: list[tuple],
    question: str,
) -> tuple[str, list[SourceCitation]]:
    """Return all unique pages represented in retrieved evidence."""
    page_rows: dict[tuple[uuid.UUID, int | None], tuple] = {}
    for chunk, doc, dist in rows:
        key = (doc.id, chunk.page_number)
        if key not in page_rows or dist < page_rows[key][2]:
            page_rows[key] = (chunk, doc, dist)

    ordered = sorted(
        page_rows.values(),
        key=lambda row: (
            row[1].original_name.lower(),
            row[0].page_number is None,
            row[0].page_number or 10**9,
        ),
    )

    if not ordered:
        return NO_RELEVANT_MSG, []

    pages_by_doc: dict[str, list[str]] = {}
    citations: list[SourceCitation] = []
    for chunk, doc, dist in ordered:
        page_label = str(chunk.page_number) if chunk.page_number else "N/A"
        pages_by_doc.setdefault(doc.original_name, []).append(page_label)
        citations.append(
            SourceCitation(
                document_id=doc.id,
                document_name=doc.original_name,
                page_number=chunk.page_number,
                score=round(1.0 - float(dist), 4),
                domain_name=getattr(doc, "domain_name", None),
                chunk_id=chunk.id,
                highlight_text=(chunk.content or "").strip()[:500] or None,
            )
        )

    lines = ["**Pages containing matching information:**"]
    ref = 1
    for doc_name, pages in pages_by_doc.items():
        unique_pages = list(dict.fromkeys(pages))
        refs = [f"[{i}]" for i in range(ref, ref + len(unique_pages))]
        ref += len(unique_pages)
        lines.append(f"- **{doc_name}:** {', '.join(unique_pages)} {' '.join(refs)}")

    lines.append("")
    lines.append("**Sources:**")
    for i, citation in enumerate(citations, 1):
        page_label = citation.page_number if citation.page_number else "N/A"
        lines.append(f"[{i}] {citation.document_name}, Page {page_label}")

    return "\n".join(lines), citations

def _calculate_confidence(chunks_with_scores: list[tuple]) -> tuple[float, str]:
    """
    Confidence score (0–100) and level derived from retrieval quality.

    Weights
    -------
    50 %  Best chunk similarity   — strongest single match in the corpus
    30 %  Average chunk similarity — overall context consistency
    20 %  Coverage ratio           — fraction of TOP_K slots filled

    Levels
    ------
    High     ≥ 80   (emerald)
    Good     60–79  (blue)
    Moderate 40–59  (amber)
    Low      < 40   (red)
    """
    if not chunks_with_scores:
        return 0.0, "low"

    similarities = [round(1.0 - float(dist), 4) for _, _, dist in chunks_with_scores]
    top_sim  = max(similarities)
    avg_sim  = sum(similarities) / len(similarities)
    # Use the appropriate target chunk count for coverage calculation:
    # when the reranker is on, we intentionally return fewer (RERANKER_TOP_K) chunks
    # so coverage should be measured against that target, not TOP_K_CHUNKS.
    target_k = settings.RERANKER_TOP_K if settings.RERANKER_ENABLED else settings.TOP_K_CHUNKS
    coverage = min(len(chunks_with_scores) / max(target_k, 1), 1.0)

    score = round(min((top_sim * 0.50 + avg_sim * 0.30 + coverage * 0.20) * 100, 100.0), 1)

    level = (
        "high"     if score >= 80 else
        "good"     if score >= 60 else
        "moderate" if score >= 40 else
        "low"
    )
    return score, level


def _retrieval_confidence_gate(
    rows: list[tuple],
    confidence_score: float,
) -> tuple[bool, str, dict]:
    """
    Decide whether retrieved chunks are good enough to send to the LLM.

    Called AFTER all reranking so `dist` in each row equals (1 - cross_encoder_score)
    when the cross-encoder is enabled, or cosine distance when it is not.

    Returns
    -------
    (should_block, reason, score_details)
    should_block = True  → return structured Not Found, skip LLM
    should_block = False → proceed to LLM generation

    Gate conditions (all configurable via config.py / .env):
    ────────────────────────────────────────────────────────
    G1  best_sim < CONFIDENCE_GATE_ABSOLUTE_MIN
        The strongest retrieved chunk is near-orthogonal to the question.
        At this level the documents contain no signal for this topic.

    G2  composite confidence_score < CONFIDENCE_GATE_SCORE_MIN
        The weighted blend of best-sim / avg-sim / coverage is too low.
        The retrieval pool is too noisy to generate a reliable answer.

    G3  No chunk ≥ CONFIDENCE_GATE_HIGH_QUALITY_SIM AND best_sim < 0.40
        Nothing in the retrieved set directly answers the question and
        the best candidate is only marginally related (borderline zone).
        This catches "maternity leave asked against a VPN-only corpus" style
        failures that G1 and G2 miss when a moderately related topic exists.
    """
    if not settings.CONFIDENCE_GATE_ENABLED or not rows:
        return False, "", {}

    similarities = [round(1.0 - float(dist), 4) for _, _, dist in rows]
    best_sim          = max(similarities)
    avg_sim           = sum(similarities) / len(similarities)
    high_quality_cnt  = sum(1 for s in similarities if s >= settings.CONFIDENCE_GATE_HIGH_QUALITY_SIM)
    n_rows            = len(rows)

    score_details = {
        "best_sim":         round(best_sim, 4),
        "avg_sim":          round(avg_sim, 4),
        "composite":        round(confidence_score, 1),
        "high_quality_cnt": high_quality_cnt,
        "chunks_evaluated": len(rows),
        "min_relevance_score": settings.RETRIEVAL_MIN_RELEVANCE_SCORE,
    }

    if best_sim < settings.RETRIEVAL_MIN_RELEVANCE_SCORE:
        return (
            True,
            f"G0:min_relevance - best_sim={best_sim:.3f} < {settings.RETRIEVAL_MIN_RELEVANCE_SCORE}",
            score_details,
        )

    # G1 — absolute noise
    if best_sim < settings.CONFIDENCE_GATE_ABSOLUTE_MIN:
        return (
            True,
            f"G1:absolute_noise — best_sim={best_sim:.3f} < {settings.CONFIDENCE_GATE_ABSOLUTE_MIN}",
            score_details,
        )

    # G2 — composite score too low
    if confidence_score < settings.CONFIDENCE_GATE_SCORE_MIN:
        return (
            True,
            f"G2:low_composite — score={confidence_score:.1f} < {settings.CONFIDENCE_GATE_SCORE_MIN}",
            score_details,
        )

    # G3 — no high-quality chunk + marginal best
    if high_quality_cnt == 0 and best_sim < 0.40:
        return (
            True,
            f"G3:no_quality_chunk — high_quality=0 and best_sim={best_sim:.3f} < 0.40",
            score_details,
        )

    return False, "", score_details


async def _fetch_scope_chunks_by_order(
    *,
    user_id,
    scope_type: str,
    scope_id,
    scope_name: str | None,
    limit: int,
    db,
) -> list[tuple]:
    """
    Fallback for summary/list/pageagg when embedding retrieval returns nothing.

    Pulls chunks directly from the scoped document(s) ordered by
    (document_id, chunk_index) — no similarity filter — so a generic query
    like "Summarize the chapter" always has material to work with.

    Returns rows shaped like the retriever's output:
        list[(DocumentChunk, Document, distance)]
    where distance is a placeholder 0.5 (used only for relevance tiering).
    """
    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
    )
    if scope_type == "folder" and scope_id:
        stmt = stmt.where(Document.folder_id == scope_id)
    elif scope_type == "document" and scope_id:
        stmt = stmt.where(Document.id == scope_id)
    elif scope_type == "domain" and scope_name:
        stmt = stmt.where(Document.domain_name == scope_name)

    stmt = stmt.order_by(
        Document.id,
        DocumentChunk.chunk_index.asc(),
    ).limit(limit)

    result = await db.execute(stmt)
    rows: list[tuple] = []
    for chunk, doc in result.all():
        # Placeholder distance — relevance tiering will mark these "MEDIUM".
        rows.append((chunk, doc, 0.5))
    return rows


def _not_found_gated_response(
    question: str,
    rows: list[tuple],
    score_details: dict,
    gate_reason: str,
) -> str:
    """
    User-facing Not Found response emitted when the confidence gate fires.

    Retrieval diagnostics (best similarity, chunk count, gate reason) stay in
    backend logs. The user sees a clean message, a coverage hint derived from
    the retrieved rows so they can tell *what* the corpus does cover, and
    suggestions.
    """
    headings: list[str] = []
    docs: list[str] = []
    seen_heading: set[str] = set()
    seen_doc: set[str] = set()
    for chunk, doc, _dist in (rows or [])[:8]:
        h = (getattr(chunk, "section_heading", None) or "").strip()
        if h and h.lower() not in seen_heading:
            seen_heading.add(h.lower())
            headings.append(h)
        name = getattr(doc, "original_name", None)
        if name and name not in seen_doc:
            seen_doc.add(name)
            docs.append(name)

    coverage_line = ""
    if headings:
        sample = ", ".join(headings[:5])
        coverage_line = (
            f"\n**The retrieved sections cover:** {sample}\n"
            "Your question does not match any of these topics.\n"
        )
    elif docs:
        sample = ", ".join(docs[:3])
        coverage_line = (
            f"\n**Documents searched:** {sample}\n"
            "None contained content matching your question.\n"
        )

    return (
        "**Answer:**\n"
        "The uploaded documents do not contain enough information to answer this question.\n"
        f"{coverage_line}\n"
        "**Suggestions:**\n"
        "- Rephrase the question using keywords that appear in your documents.\n"
        "- Upload a document that covers this topic.\n"
        "- Try a broader question to confirm what is covered.\n\n"
        "**Confidence:** Low"
    )


def _relevance_tier(dist: float) -> str:
    """Map cosine distance to a human-readable relevance label."""
    if dist <= 0.25:
        return "HIGH"
    if dist <= 0.45:
        return "MEDIUM"
    return "LOW"


def _validate_sources(chunks_with_scores: list[tuple]) -> list[tuple]:
    """
    Pre-generation source validation.

    Filters out chunks that would produce unreliable citations:
      - Null or near-empty content (< 20 chars)
      - Missing document reference
      - Page number 0 is allowed but flagged (known DOCX table limitation)

    Returns the validated list (never raises — logs warnings for bad chunks).
    """
    validated: list[tuple] = []
    dropped = 0
    for chunk, doc, dist in chunks_with_scores:
        content = (chunk.content or '').strip()
        if not content or len(content) < 20:
            logger.warning(
                f"[SourceVal] Dropping chunk with near-empty content  "
                f"chunk_id={chunk.id}  doc={doc.original_name!r}  len={len(content)}"
            )
            dropped += 1
            continue
        if not doc or not getattr(doc, 'original_name', None):
            logger.warning(
                f"[SourceVal] Dropping chunk with missing document reference  "
                f"chunk_id={chunk.id}"
            )
            dropped += 1
            continue
        if chunk.page_number == 0:
            logger.info(
                f"[SourceVal] Page number 0 detected  "
                f"chunk_id={chunk.id}  doc={doc.original_name!r}  "
                "(legacy DOCX ingestion — citation will show 'N/A')"
            )
        validated.append((chunk, doc, dist))

    if dropped:
        logger.info(
            f"[SourceVal] Validation complete — kept {len(validated)}, "
            f"dropped {dropped} invalid chunk(s)"
        )
    return validated


def _format_context(
    chunks_with_scores: list[tuple],
) -> tuple[str, list[SourceCitation]]:
    """
    Build a numbered, graded context block and deduplicated source citations.

    The block includes:
      • A MANIFEST listing every contributing document and chunk count,
        giving the model an explicit map of what evidence exists.
      • A per-chunk RELEVANCE tier (HIGH / MEDIUM / LOW) derived from cosine
        distance, so the model can weight claims proportionally to evidence
        quality rather than treating all chunks as equally authoritative.
      • Numbered excerpts [1]…[N] that the model is instructed to cite inline,
        making every factual claim traceable back to a specific source.
    """
    context_parts: list[str] = []
    sources: list[SourceCitation] = []
    seen: set[str] = set()

    # Build manifest: doc_name → (chunk count, summary snippet, domain)
    doc_meta: dict[str, dict] = {}
    for _, doc, _ in chunks_with_scores:
        name = doc.original_name
        if name not in doc_meta:
            doc_meta[name] = {
                "count":   0,
                "summary": getattr(doc, "summary", None) or "",
                "domain":  getattr(doc, "domain_name", None) or "",
            }
        doc_meta[name]["count"] += 1

    unique_docs  = len(doc_meta)
    total_chunks = len(chunks_with_scores)

    if unique_docs > 1:
        manifest_lines = [
            f"RETRIEVED CONTEXT — {total_chunks} excerpt(s) from {unique_docs} documents",
            "Synthesize a single answer from ALL relevant excerpts below regardless of which document they come from.",
        ]
    else:
        manifest_lines = [
            f"RETRIEVED CONTEXT — {total_chunks} excerpt(s) from {unique_docs} document(s)",
        ]

    for doc_name, meta in doc_meta.items():
        cnt        = meta["count"]
        chunk_word = "excerpt" if cnt == 1 else "excerpts"
        domain_tag = f"  [{meta['domain']}]" if meta["domain"] else ""
        summary_tag = ""
        if meta["summary"]:
            snip = meta["summary"].strip()[:120].replace("\n", " ")
            summary_tag = f"  — {snip}{'…' if len(meta['summary']) > 120 else ''}"
        manifest_lines.append(f"  • {doc_name}{domain_tag}  ({cnt} {chunk_word}){summary_tag}")
    manifest = "\n".join(manifest_lines)

    for i, (chunk, doc, dist) in enumerate(chunks_with_scores, 1):
        similarity = round(1.0 - float(dist), 4)
        page_label = str(chunk.page_number) if chunk.page_number else "N/A"
        tier = _relevance_tier(dist)
        category = getattr(chunk, "category", None) or getattr(doc, "domain_name", None) or "General"
        source_document = getattr(chunk, "source_document", None) or doc.original_name
        section_heading = getattr(chunk, "section_heading", None) or ""
        section_tag = f" | Section: {section_heading}" if section_heading else ""

        context_parts.append(
            f"[{i}] {doc.original_name} | Page: {page_label}{section_tag} | "
            f"Chunk: {chunk.id} | Source: {source_document} | "
            f"Category: {category} | Relevance: {tier}\n"
            f"{chunk.content.strip()}"
        )

        key = f"{doc.id}:{chunk.page_number}"
        if key not in seen:
            sources.append(
                SourceCitation(
                    document_id=doc.id,
                    document_name=doc.original_name,
                    page_number=chunk.page_number,
                    score=similarity,
                    domain_name=getattr(doc, "domain_name", None),
                    chunk_id=chunk.id,
                    highlight_text=chunk.content.strip()[:500] if chunk.content else None,
                )
            )
            seen.add(key)

    divider = "─" * 56
    body = f"\n{divider}\n\n".join(context_parts)
    return (
        f"<context>\n{manifest}\n{divider}\n\n{body}\n\n{divider}\n</context>",
        sources,
    )


def _retrieval_debug_payload(rows: list[tuple]) -> dict:
    scores = [round(1.0 - float(dist), 4) for _, _, dist in rows]
    return {
        "top_k": settings.RERANKER_TOP_K if settings.RERANKER_ENABLED else settings.TOP_K_CHUNKS,
        "chunk_count": len(rows),
        "average_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "min_relevance_score": settings.RETRIEVAL_MIN_RELEVANCE_SCORE,
        "reranker": {
            "enabled": settings.RERANKER_ENABLED,
            "backend": settings.RERANKER_BACKEND,
            "model": settings.RERANKER_MODEL,
        },
        "chunks": [
            {
                "chunk_id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "document_id": str(doc.id),
                "document_name": doc.original_name,
                "source_document": getattr(chunk, "source_document", None) or doc.original_name,
                "page_number": chunk.page_number,
                "section": getattr(chunk, "section_heading", None),
                "score": round(1.0 - float(dist), 4),
                "distance": round(float(dist), 4),
                "embedding_model": getattr(chunk, "embedding_model", None),
                "embedding_version": getattr(chunk, "embedding_version", None),
                "preview": (chunk.content or "").strip()[:500],
            }
            for chunk, doc, dist in rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic top-K
# ─────────────────────────────────────────────────────────────────────────────

def _dynamic_top_k(question: str, avg_similarity: float) -> int:
    """Return the number of candidates to fetch for the reranker input pool.

    Base = RERANKER_INPUT_SIZE (20).  Long questions get +4 for broader
    coverage before the cross-encoder cuts to RERANKER_TOP_K.
    Result is clamped to [RERANKER_TOP_K, VECTOR_SEARCH_CANDIDATES].
    """
    base = settings.RERANKER_INPUT_SIZE
    word_count = len(question.split())
    extra = 4 if word_count > 15 else 0
    return max(settings.RERANKER_TOP_K, min(base + extra, settings.VECTOR_SEARCH_CANDIDATES))


# ─────────────────────────────────────────────────────────────────────────────
# Keyword (FTS) search
# ─────────────────────────────────────────────────────────────────────────────

async def _keyword_search(
    question: str,
    user_id: uuid.UUID,
    db: AsyncSession,
    scope_type: str = "all",
    scope_id: uuid.UUID | None = None,
    scope_name: str | None = None,
    limit: int | None = None,
) -> list[tuple]:
    """
    PostgreSQL full-text search over document_chunks.content.

    Returns a list of (DocumentChunk, Document) tuples ranked by ts_rank.
    Falls back gracefully (returns []) when FTS is unavailable or the query fails.
    """
    if not settings.HYBRID_SEARCH_ENABLED:
        return []

    try:
        query = func.plainto_tsquery("english", question)
        vector = func.to_tsvector("english", DocumentChunk.content)
        fts_filter = vector.op("@@")(query)
        ts_rank_expr = func.ts_rank(vector, query)

        stmt = (
            select(DocumentChunk, Document)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.indexed)
            .where(DocumentChunk.embedding.is_not(None))
            .where(fts_filter)
        )

        if scope_type == "folder" and scope_id:
            stmt = stmt.where(Document.folder_id == scope_id)
        elif scope_type == "document" and scope_id:
            stmt = stmt.where(Document.id == scope_id)
        elif scope_type == "domain" and scope_name:
            stmt = stmt.where(Document.domain_name == scope_name)

        stmt = stmt.order_by(ts_rank_expr.desc()).limit(limit or settings.TOP_K_CHUNKS * 2)  # noqa: E501

        rows = await db.execute(stmt)
        return list(rows.all())

    except Exception as exc:
        logger.warning(f"[RAG] FTS keyword search failed (non-fatal): {exc}")
        return []


def _rrf_fuse_results(
    vector_results: list[tuple],
    keyword_results: list[tuple],
    *,
    rrf_k: int | None = None,
) -> tuple[list[tuple], dict[str, int]]:
    """
    Fuse vector-ranked and keyword-ranked candidates with Reciprocal Rank Fusion.

    Input rows are already ranked within each retriever:
      vector_results  -> (DocumentChunk, Document, distance), lower distance first
      keyword_results -> (DocumentChunk, Document), PostgreSQL ts_rank order

    The returned rows keep the existing (chunk, doc, distance) shape. Distance is
    derived from normalized RRF score so downstream reranking and citations can
    continue without a new row type.
    """
    if not vector_results and not keyword_results:
        return [], {"vector": 0, "keyword": 0, "overlap": 0, "keyword_only": 0}

    k = rrf_k if rrf_k is not None else settings.HYBRID_SEARCH_RRF_K
    candidate_map: dict[uuid.UUID, tuple] = {}
    scores: dict[uuid.UUID, float] = {}
    vector_ids: set[uuid.UUID] = set()
    keyword_ids: set[uuid.UUID] = set()

    for rank, (chunk, doc, dist) in enumerate(vector_results, start=1):
        cid = chunk.id
        vector_ids.add(cid)
        candidate_map.setdefault(cid, (chunk, doc, dist))
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank))

    for rank, (chunk, doc) in enumerate(keyword_results, start=1):
        cid = chunk.id
        keyword_ids.add(cid)
        if cid not in candidate_map:
            candidate_map[cid] = (chunk, doc, None)
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank))

    max_score = max(scores.values(), default=1.0)
    fused: list[tuple] = []
    for cid, (chunk, doc, _dist) in candidate_map.items():
        normalized = scores[cid] / max_score if max_score else 0.0
        fused_dist = max(0.0, min(0.99, 1.0 - normalized))
        fused.append((chunk, doc, fused_dist))

    fused.sort(
        key=lambda item: (
            -scores[item[0].id],
            item[0].id not in keyword_ids,
            item[0].id not in vector_ids,
        )
    )

    overlap = len(vector_ids & keyword_ids)
    stats = {
        "vector": len(vector_results),
        "keyword": len(keyword_results),
        "overlap": overlap,
        "keyword_only": len(keyword_ids - vector_ids),
    }
    return fused, stats


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval (hybrid)
# ─────────────────────────────────────────────────────────────────────────────

async def _retrieve_chunks(
    query_embeddings: list[list[float]],
    user_id: uuid.UUID,
    db: AsyncSession,
    scope_type: str = "all",
    scope_id: uuid.UUID | None = None,
    question: str = "",
    scope_name: str | None = None,
    distance_threshold: float | None = None,
) -> list[tuple]:
    """
    Hybrid retrieval: multi-vector cosine search + PostgreSQL FTS keyword search.

    Multi-query vector search (new):
      query_embeddings is a list of N vectors, one per search variant.
      For each chunk the distance used is min(dist(qv, chunk) for qv in variants).
      This finds chunks that match ANY semantic angle rather than only the primary
      query angle, significantly improving recall for terminology-diverse documents.

    Algorithm:
    1. Run cosine-distance vector search across all N query variants.
    2. If HYBRID_SEARCH_ENABLED, run FTS keyword search.
    3. Fuse vector and keyword rankings with Reciprocal Rank Fusion (RRF).
    4. Deduplicate fused candidates and return top-K for the reranker.

    Deduplication passes (applied after sorting by relevance):
      1. One chunk per (document_id, page_number) — keeps the best-ranked chunk
         per page so overlapping chunks don't flood the same content.
      2. Content fingerprint — drops chunks whose first 150 chars are identical.
    """
    # ── Pre-flight: filter diagnostic ────────────────────────────────────────
    # Run fast COUNT queries at every filter layer before the expensive
    # vector scan.  Shows exactly which WHERE clause is eliminating chunks.
    page_agg_query = _is_page_aggregation_query(question)
    await _count_eligible_chunks(
        user_id, db, scope_type, scope_id, scope_name
    )

    # ── Step 1: Vector (cosine) search ────────────────────────────────────────
    _scope_desc = (
        f"folder={scope_id}"     if scope_type == "folder"   and scope_id   else
        f"document={scope_id}"   if scope_type == "document" and scope_id   else
        f"domain={scope_name!r}" if scope_type == "domain"   and scope_name else
        "all"
    )
    logger.info(
        f"[FILTER] Building vector query — "
        f"user={user_id}  scope_type={scope_type!r}  scope={_scope_desc}  "
        f"status=indexed  embedding=NOT NULL"
    )

    stmt = (
        select(DocumentChunk, Document)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
        .where(DocumentChunk.embedding.is_not(None))
    )

    if scope_type == "folder" and scope_id:
        stmt = stmt.where(Document.folder_id == scope_id)
        logger.info(f"[FILTER] ✦ Folder filter applied  — folder_id={scope_id}")
    elif scope_type == "document" and scope_id:
        stmt = stmt.where(Document.id == scope_id)
        logger.info(f"[FILTER] ✦ Document filter applied — document_id={scope_id}")
    elif scope_type == "domain" and scope_name:
        stmt = stmt.where(Document.domain_name == scope_name)
        logger.info(f"[FILTER] ✦ Domain filter applied   — domain_name={scope_name!r}")
    else:
        logger.info("[FILTER] ✦ No scope filter — searching ALL documents for this user")

    # ── pgvector native ORDER BY (when extension is installed) ───────────────
    # Multi-query: run one ORDER BY query per variant and union the candidates.
    # Without pgvector: fetch all rows once, then compute min-distance in Python.
    primary_embedding = query_embeddings[0]

    max_dist = (
        distance_threshold
        if distance_threshold is not None
        else settings.MAX_RETRIEVAL_DISTANCE
    )

    vector_scored: list[tuple] = []
    dim_mismatches  = 0
    null_embeddings = 0
    above_threshold = 0

    if _pv.is_available():
        # Per-variant query — each returns at most VECTOR_SEARCH_CANDIDATES rows.
        # Candidates across variants are unioned by chunk ID; each chunk keeps the
        # minimum distance seen across all variant queries.
        candidate_map: dict = {}   # chunk.id -> (chunk, doc)
        min_dist_map:  dict = {}   # chunk.id -> float (best distance so far)

        logger.debug(
            f"[pgvector] Multi-query: {len(query_embeddings)} variant(s) "
            f"× LIMIT {settings.VECTOR_SEARCH_CANDIDATES} each"
        )
        for _qi, qv in enumerate(query_embeddings):
            vec_str    = ','.join(f'{v:.8f}' for v in qv)
            order_expr = text(f"embedding::vector <=> '[{vec_str}]'::vector")
            variant_stmt = stmt.order_by(order_expr).limit(settings.VECTOR_SEARCH_CANDIDATES)
            variant_rows = (await db.execute(variant_stmt)).all()
            for chunk, doc in variant_rows:
                if chunk.id not in candidate_map:
                    candidate_map[chunk.id] = (chunk, doc)
                # Compute exact cosine distance for this variant
                if chunk.embedding is not None and len(chunk.embedding) == len(qv):
                    d = _cosine_distance(qv, chunk.embedding)
                    if chunk.id not in min_dist_map or d < min_dist_map[chunk.id]:
                        min_dist_map[chunk.id] = d
            logger.debug(
                f"[pgvector]   variant[{_qi}] → {len(variant_rows)} rows  "
                f"total_unique_so_far={len(candidate_map)}"
            )

        total_rows = len(candidate_map)
        for cid, (chunk, doc) in candidate_map.items():
            if chunk.embedding is None:
                null_embeddings += 1
                continue
            stored_dim = len(chunk.embedding)
            q_dim      = len(primary_embedding)
            if stored_dim != q_dim:
                if dim_mismatches == 0:
                    logger.warning(
                        f"[RAG] EMBEDDING DIM MISMATCH — stored={stored_dim} query={q_dim} "
                        f"chunk_id={chunk.id} doc={doc.original_name!r}. "
                        "Re-index all documents to fix."
                    )
                dim_mismatches += 1
                continue
            dist = min_dist_map.get(cid, _cosine_distance(primary_embedding, chunk.embedding))
            if dist < max_dist:
                above_threshold += 1
                vector_scored.append((chunk, doc, dist))

    else:
        # Python cosine path — load all rows once, score against every variant.
        rows     = await db.execute(stmt)
        all_rows = rows.all()
        total_rows = len(all_rows)
        for chunk, doc in all_rows:
            if chunk.embedding is None:
                null_embeddings += 1
                continue
            stored_dim = len(chunk.embedding)
            q_dim      = len(primary_embedding)
            if stored_dim != q_dim:
                if dim_mismatches == 0:
                    logger.warning(
                        f"[RAG] EMBEDDING DIM MISMATCH — stored={stored_dim} query={q_dim} "
                        f"chunk_id={chunk.id} doc={doc.original_name!r}. "
                        "Re-index all documents to fix."
                    )
                dim_mismatches += 1
                continue
            # Take the minimum distance across all variant vectors (best match wins)
            dist = min(_cosine_distance(qv, chunk.embedding) for qv in query_embeddings)
            if dist < max_dist:
                above_threshold += 1
                vector_scored.append((chunk, doc, dist))

    logger.info(
        f"[RAG] Cosine scan  : variants={len(query_embeddings)}  total={total_rows}  "
        f"null_emb={null_embeddings}  dim_mismatch={dim_mismatches}  "
        f"pass_threshold={above_threshold}  threshold={max_dist}"
    )
    if dim_mismatches:
        logger.error(
            f"[RAG] CRITICAL — {dim_mismatches} chunks have wrong embedding dimension. "
            "All retrieval will fail. Fix: DELETE FROM document_chunks; "
            "UPDATE documents SET status='pending'; then restart server."
        )

    # Sort and cap at VECTOR_SEARCH_CANDIDATES before the hybrid merge step
    vector_scored.sort(key=lambda x: x[2])
    vector_scored = vector_scored[:settings.VECTOR_SEARCH_CANDIDATES]

    # ── P4: Section metadata boost ────────────────────────────────────────────
    # If the query belongs to a recognisable section domain (travel, leave, …),
    # reduce the distance of chunks whose section_heading matches that domain.
    # This raises domain-relevant chunks in the reranker input pool without
    # hard-filtering out other chunks (fallback-safe).
    _sec_hint = _extract_section_hint(question) if question else None
    if _sec_hint and vector_scored:
        _boost      = settings.SECTION_METADATA_BOOST
        _hint_words = _SECTION_HINT_WORDS.get(_sec_hint, [])
        _boosted    = 0
        for _i, (_ch, _dc, _d) in enumerate(vector_scored):
            _heading = (getattr(_ch, 'section_heading', '') or '').lower()
            if _heading and any(_w in _heading for _w in _hint_words):
                vector_scored[_i] = (_ch, _dc, max(0.0, _d - _boost))
                _boosted += 1
        if _boosted:
            vector_scored.sort(key=lambda x: x[2])
            logger.info(
                f"[MetaBoost] section_hint={_sec_hint!r}  "
                f"boosted {_boosted} chunk(s) by -{_boost:.2f}"
            )

    logger.info(
        f"[FILTER] After cosine threshold ({max_dist})  : "
        f"{len(vector_scored)} / {total_rows} chunks passed  "
        f"(dropped {total_rows - len(vector_scored)})"
    )
    if vector_scored:
        _best  = round(1.0 - vector_scored[0][2],  4)
        _worst = round(1.0 - vector_scored[-1][2], 4)
        logger.info(
            f"[FILTER] Similarity range after threshold  : "
            f"best={_best}  worst={_worst}"
        )

    # ── Step 2: Keyword (FTS) search — full query + per-term fallback ─────────
    keyword_results: list[tuple] = []
    if settings.HYBRID_SEARCH_ENABLED and question:
        keyword_limit = settings.VECTOR_SEARCH_CANDIDATES if page_agg_query else None
        # Full-phrase search (plainto_tsquery ANDs all terms)
        keyword_results = await _keyword_search(
            question, user_id, db, scope_type, scope_id, scope_name,
            limit=keyword_limit,
        )
        # Per-term search so multi-hop answers aren't killed by AND semantics.
        # E.g. "internal codename BookWrench" → also search "codename" alone.
        seen_kw_ids = {chunk.id for chunk, _ in keyword_results}
        for rewrite in _query_phrase_rewrites(question):
            rewrite_rows = await _keyword_search(
                rewrite, user_id, db, scope_type, scope_id, scope_name,
                limit=keyword_limit,
            )
            for chunk, doc in rewrite_rows:
                if chunk.id not in seen_kw_ids:
                    seen_kw_ids.add(chunk.id)
                    keyword_results.append((chunk, doc))
        q_terms = [
            w.strip('?.,!;:\'\"')
            for w in question.split()
            if len(w) > 2 and w.lower().strip('?.,!;:') not in _STOP_WORDS
        ]

        # Also include synonym terms so "vacation" matches "pto", "CEO" matches
        # "Chief Executive Officer", etc.
        synonym_search_terms: list[str] = []
        for term in q_terms[:6]:
            for syn in _QUERY_SYNONYMS.get(term.lower(), [])[:2]:
                first = syn.split()[0]
                if len(first) > 3 and first.lower() not in _STOP_WORDS:
                    synonym_search_terms.append(first)

        all_kw_terms = q_terms[:6] + synonym_search_terms[:4]

        for term in all_kw_terms:
            term_rows = await _keyword_search(
                term, user_id, db, scope_type, scope_id, scope_name,
                limit=keyword_limit,
            )
            for chunk, doc in term_rows:
                if chunk.id not in seen_kw_ids:
                    seen_kw_ids.add(chunk.id)
                    keyword_results.append((chunk, doc))

    # Build a set of chunk IDs from keyword results for O(1) lookup
    logger.info(
        f"[FILTER] FTS keyword results   : {len(keyword_results)} chunks  "
        f"(hybrid={'enabled' if settings.HYBRID_SEARCH_ENABLED else 'disabled'})"
    )

    vector_scored, vector_meta = _metadata_filter_rows(vector_scored, question)
    keyword_results, keyword_meta = _metadata_filter_rows(keyword_results, question)
    if vector_meta["allowed_categories"]:
        logger.info(
            f"[FILTER] Metadata category   : allowed={vector_meta['allowed_categories']}  "
            f"vector={vector_meta['matched']}/{vector_meta['original']} "
            f"({'applied' if vector_meta['enabled'] else 'fallback'})  "
            f"keyword={keyword_meta['matched']}/{keyword_meta['original']} "
            f"({'applied' if keyword_meta['enabled'] else 'fallback'})"
        )

    # Step 3: fuse vector and keyword ranks with RRF.
    fused, fusion_stats = _rrf_fuse_results(vector_scored, keyword_results)
    logger.info(
        f"[FILTER] After RRF fusion      : {len(fused)} candidates  "
        f"(vector={fusion_stats['vector']}  keyword={fusion_stats['keyword']}  "
        f"overlap={fusion_stats['overlap']}  "
        f"keyword_only={fusion_stats['keyword_only']}  k={settings.HYBRID_SEARCH_RRF_K})"
    )
    # Calculate avg_similarity for dynamic top-K (use pre-boost distances to be honest)
    avg_similarity = 0.0
    if vector_scored:
        avg_similarity = sum(1.0 - d for _, _, d in vector_scored) / len(vector_scored)

    top_k = settings.VECTOR_SEARCH_CANDIDATES if page_agg_query else _dynamic_top_k(question, avg_similarity)

    # Pass 1: up to MAX_CHUNKS_PER_PAGE chunks per (document_id, page_number).
    page_counts: dict[str, int] = {}
    page_limit  = 1 if page_agg_query else settings.MAX_CHUNKS_PER_PAGE
    page_deduped: list[tuple] = []
    _page_dropped: list[tuple] = []
    for item in fused:
        key = f"{item[1].id}:{item[0].page_number}"
        n   = page_counts.get(key, 0)
        if n < page_limit:
            page_counts[key] = n + 1
            page_deduped.append(item)
        else:
            _page_dropped.append(item)

    logger.info(
        f"[FILTER] After page dedup      : {len(page_deduped)} chunks  "
        f"(dropped {len(_page_dropped)} — exceeded MAX_CHUNKS_PER_PAGE={page_limit})"
    )
    if _page_dropped:
        logger.info(
            f"[FILTER]   Page-dedup dropped chunks (may include answer):"
        )
        for _c, _d, _dist in _page_dropped[:5]:
            logger.info(
                f"[FILTER]     sim={round(1-_dist,4):.4f}  "
                f"page={_c.page_number}  doc={_d.original_name!r}  "
                f"preview={(_c.content or '')[:80]!r}"
            )

    # Pass 2: remove near-duplicate content by fingerprinting first 150 chars
    seen_content: set[int] = set()
    unique: list[tuple] = []
    _content_dropped: list[tuple] = []
    for item in page_deduped:
        if page_agg_query:
            unique.append(item)
            continue
        fingerprint = hash(item[0].content.strip()[:150].lower())
        if fingerprint not in seen_content:
            seen_content.add(fingerprint)
            unique.append(item)
        else:
            _content_dropped.append(item)

    logger.info(
        f"[FILTER] After content dedup   : {len(unique)} chunks  "
        f"(dropped {len(_content_dropped)} near-duplicate chunks)"
    )

    # ── top-K analysis ────────────────────────────────────────────────────────
    _q_words    = len(question.split()) if question else 0
    _intent_k   = _INTENT_TOP_K.get(_intent_classify(question), settings.RERANKER_TOP_K) \
                  if question else settings.RERANKER_TOP_K
    _dynamic_k  = top_k
    _pre_rerank = len(unique)
    _final_k    = min(_pre_rerank, _dynamic_k)

    logger.info(
        f"[FILTER] Top-K analysis        : "
        f"dynamic_top_k={_dynamic_k}  "
        f"intent_top_k={_intent_k}  "
        f"RERANKER_TOP_K={settings.RERANKER_TOP_K}  "
        f"TOP_K_CHUNKS={settings.TOP_K_CHUNKS}  "
        f"question_words={_q_words}"
    )
    logger.info(
        f"[FILTER] Pre-rerank pool       : {_pre_rerank} chunks  "
        f"→ top-K cut will keep {_final_k}  "
        f"(dropping {_pre_rerank - _final_k} at this stage)"
    )

    # ── Threshold analysis ────────────────────────────────────────────────────
    _sim_bands = {"≥0.75": 0, "0.50–0.74": 0, "0.25–0.49": 0, "<0.25": 0}
    for _, _, _d in unique:
        _s = 1.0 - float(_d)
        if   _s >= 0.75: _sim_bands["≥0.75"]    += 1
        elif _s >= 0.50: _sim_bands["0.50–0.74"] += 1
        elif _s >= 0.25: _sim_bands["0.25–0.49"] += 1
        else:            _sim_bands["<0.25"]      += 1
    logger.info(f"[FILTER] Similarity distribution  : {_sim_bands}")

    if unique and max(1.0 - float(d) for _, _, d in unique) < 0.30:
        logger.warning(
            "[FILTER] ⚠ ALL CHUNKS HAVE LOW SIMILARITY (< 0.30)  "
            "Possible causes: "
            "(1) embedding dimension mismatch, "
            "(2) document uses very different vocabulary from the question, "
            "(3) question is about a topic not in the indexed documents."
        )

    return unique[:top_k]


# ─────────────────────────────────────────────────────────────────────────────
# Conversation history
# ─────────────────────────────────────────────────────────────────────────────

async def _build_conversation_context(
    session_id: uuid.UUID,
    user_msg_created_at: datetime,
    db: AsyncSession,
) -> list[dict]:
    """
    Fetch the last CONVERSATION_HISTORY_LIMIT messages created before
    user_msg_created_at in this session, and return them as a list of dicts
    suitable for passing to the AI provider.

    Format: [{"role": "user"|"assistant", "content": str}, …]  (oldest first)
    Assistant messages are truncated to 400 chars to limit token usage.
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.created_at < user_msg_created_at)
        .order_by(ChatMessage.created_at.desc())
        .limit(settings.CONVERSATION_HISTORY_LIMIT)
    )
    rows = (await db.execute(stmt)).scalars().all()
    # rows are newest-first; reverse to oldest-first for the AI provider
    rows = list(reversed(rows))

    history: list[dict] = []
    for msg in rows:
        content = msg.content
        if msg.role == MessageRole.assistant.value and len(content) > 800:
            content = content[:800] + "…"
        history.append({"role": msg.role, "content": content})

    return history


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_session(
    session_id: uuid.UUID | None,
    user_id: uuid.UUID,
    db: AsyncSession,
    scope_type: str = "all",
    scope_id: uuid.UUID | None = None,
    scope_name: str | None = None,
) -> ChatSession:
    if session_id:
        session = await db.get(ChatSession, session_id)
        if not session or session.user_id != user_id:
            raise NotFoundError("Chat session")
        return session
    session = ChatSession(
        user_id=user_id,
        scope_type=scope_type,
        scope_id=scope_id,
        scope_name=scope_name,
    )
    db.add(session)
    await db.flush()
    return session


# ─────────────────────────────────────────────────────────────────────────────
# Main streaming entry-point
# ─────────────────────────────────────────────────────────────────────────────

async def stream_query(
    request: ChatQueryRequest,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """Public entrypoint with a safety wrapper around _stream_query_inner.

    Any exception that escapes the inner generator is caught here, logged
    with a request ID and full stack, and translated into a clean SSE
    'error' + 'done' pair so the client never sees a torn connection.
    """
    import secrets
    import traceback as _tb

    request_id = secrets.token_hex(6)
    _safe_seen_token = False
    _safe_seen_done  = False

    def _sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    try:
        async for chunk in _stream_query_inner(request, user_id, db, request_id):
            # Defend against the inner generator yielding None (would crash
            # StreamingResponse with a TypeError).
            if chunk is None:
                logger.warning(f"[Stream {request_id}] inner generator yielded None — skipped")
                continue
            if 'event: done' in chunk:
                _safe_seen_done = True
            if 'event: token' in chunk:
                _safe_seen_token = True
            yield chunk
    except Exception as exc:
        logger.error(
            f"[Stream {request_id}] UNCAUGHT exception in stream_query — "
            f"{type(exc).__name__}: {exc}\n{_tb.format_exc()}"
        )
        # Emit a clean error + done so the client renders a user-friendly
        # message instead of "The chat stream failed on the server."
        yield _sse("error", {
            "message":        "Unable to generate response. Please check server logs.",
            "request_id":     request_id,
            "error_code":     "STREAM_FAULT",
            "exception_type": type(exc).__name__,
        })
        if not _safe_seen_done:
            yield _sse("done", {"request_id": request_id, "error": True})
        return

    # If the inner generator returned without emitting `done` (e.g. early
    # return on a non-error branch that forgot to send it), close cleanly.
    if not _safe_seen_done:
        yield _sse("done", {"request_id": request_id, "synthetic_done": True})


async def _stream_query_inner(
    request: ChatQueryRequest,
    user_id: uuid.UUID,
    db: AsyncSession,
    request_id: str = "-",
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings.
    Event types: status | confidence | token | sources | error | done
    """

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    # Defensive pre-init: these are assigned by the normal pipeline, but
    # exception handlers may reference them before the assignment runs.
    citations: list = []
    confidence_score: float = 0.0
    # embed_query is the (possibly rewritten) query used for embedding;
    # falls back to the raw question if query expansion is skipped.
    embed_query: str = request.question

    response_mode = getattr(request, "response_mode", "auto") or "auto"
    _t_start = _time.monotonic()   # wall-clock start for response_time_ms

    divider = "─" * 60
    logger.info(divider)
    logger.info(f"[RAG] ── INCOMING REQUEST ────────────────────────────────────────────")
    logger.info(f"[RAG] Question    : {request.question!r}")
    logger.info(f"[RAG] Mode        : {response_mode}")
    logger.info(f"[RAG] Session     : {request.session_id}")
    logger.info(f"[RAG] Scope       : type={request.scope_type!r}  id={request.scope_id}  name={request.scope_name!r}")
    print("Request received")

    # ── 1. Session ─────────────────────────────────────────────────────────
    try:
        session = await ensure_session(
            request.session_id,
            user_id,
            db,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            scope_name=request.scope_name,
        )
    except NotFoundError as exc:
        yield sse("error", {"message": str(exc)})
        return
    except Exception as exc:
        logger.error(f"[RAG] Session error: {exc}", exc_info=True)
        yield sse("error", {"message": "Failed to create or load chat session — database error."})
        await db.rollback()
        return

    # Use the scope stored on the session (not the request) for existing sessions
    # so scope stays consistent throughout the session's lifetime.
    scope_type = session.scope_type
    scope_id   = session.scope_id
    scope_name = session.scope_name

    yield sse("status", {"step": "thinking", "label": "Analyzing your question…"})

    # ── 2. Load recent history early (needed for follow-up query rewriting) ─
    recent_history: list[dict] = []
    if session.id:
        try:
            recent_history = await _load_recent_turns(session.id, db, limit=6)
        except Exception as exc:
            logger.warning(f"[RAG] Early history load failed (non-fatal): {exc}")

    # ── 2a. Query preparation: multi-variant generation + embedding ──────────
    # Generates 3-6 semantically distinct query strings so the vector search
    # covers multiple phrasings/angles of the user's question.  All variants
    # are batch-embedded in a single encoder call, then the retrieval step
    # computes min(distance) across all variants per chunk — a chunk is
    # returned if it's close to ANY variant, not just the primary query.
    needs_clarification, clarification_text = _needs_ambiguity_clarification(
        request.question, recent_history
    )
    if needs_clarification:
        logger.info(
            "[RAG] Ambiguous reference detected before retrieval: %r",
            request.question,
        )
        try:
            db.add(ChatMessage(
                session_id=session.id,
                role=MessageRole.user.value,
                content=request.question,
            ))
            if session.title == "New Chat":
                session.title = (
                    request.question[:60] + ("..." if len(request.question) > 60 else "")
                )
            await db.flush()
            db.add(ChatMessage(
                session_id=session.id,
                role=MessageRole.assistant.value,
                content=clarification_text,
                sources=[],
                confidence_score=0.0,
                response_mode=response_mode,
            ))
            await db.commit()
        except Exception as exc:
            logger.warning(f"[RAG] Failed to persist ambiguity clarification: {exc}")
            await db.rollback()

        yield sse("clarification", {
            "requires_context": True,
            "message": clarification_text,
        })
        yield sse("token", {"text": clarification_text})
        yield sse("sources", {
            "sources": [],
            "success": False,
            "message": clarification_text,
            "session_id": str(session.id),
        })
        yield sse("done", {
            "session_id": str(session.id),
            "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "scope_name": scope_name,
            "response_mode": response_mode,
        })
        return

    contextualized_q = _contextualize_query(request.question, recent_history)
    intent = _intent_classify(request.question)

    variants = _generate_search_variants(contextualized_q, intent)
    _trace_div = "━" * 60
    logger.info(_trace_div)
    logger.info(f"[Trace] Stage 1 — User query  : {request.question!r}")
    logger.info(f"[Trace] Stage 2 — Intent      : {intent}")
    logger.info(f"[Trace] Stage 3 — Variants    : {len(variants)} → {variants}")
    logger.info(f"[Trace] Stage 4 — Intent top_k: {_INTENT_TOP_K.get(intent, settings.RERANKER_TOP_K)}")
    logger.info(_trace_div)
    logger.info(f"[RAG] Intent      : {intent}")
    logger.info(f"[RAG] Query variants ({len(variants)}): {variants}")

    if intent == 'compliance':
        _detected_domains = _compliance_domain_variants(contextualized_q.lower())
        logger.info(
            f"[Compliance] Detected {len(_detected_domains)} policy domain(s) — "
            f"variants fan-out: {[v.split()[0:2] for v in _detected_domains]}"
        )

    try:
        embedder = get_embedder()
        # Batch-embed all variants in a single call (faster than N sequential calls)
        variant_vectors = await embedder.embed_texts(variants)
        logger.info(
            f"[RAG] Embeddings  : {len(variant_vectors)} vectors × {len(variant_vectors[0])}-dim"
        )
    except Exception as exc:
        logger.error(f"[RAG] Embedding failed: {exc}")
        yield sse("error", {"message": f"Embedding failed: {exc}"})
        await db.rollback()
        return

    yield sse("status", {"step": "searching", "label": "Searching through documents…"})

    # ── 3. Full-depth hybrid retrieval (multi-vector + keyword + entity) ───
    #
    # Design: retrieve EVERYTHING with any relevance, then re-rank.
    # The old threshold-based filter was the primary source of false negatives —
    # relevant chunks were silently dropped before the LLM ever saw them.
    # Now: hard cutoff is 0.97 (similarity < 0.03), which only excludes truly
    # orthogonal content. Relevance judgment is delegated to the LLM via the
    # tiered context labels (HIGH / MEDIUM / LOW) in the formatted context.
    rows: list[tuple] = []
    try:
        rows = await _retrieve_chunks(
            variant_vectors, user_id, db, scope_type, scope_id,
            question=request.question,
            scope_name=scope_name,
            # No explicit threshold → uses MAX_RETRIEVAL_DISTANCE (0.97)
        )
        logger.info(f"[RAG] Vector search: {len(rows)} candidate(s)")

        # Entity search — ILIKE on proper nouns, CamelCase, acronyms, quoted terms.
        # Critical for exact entity lookups ("BookWrench", "Hammer codename", etc.)
        # where the embedding distance may be deceptively high due to vocabulary mismatch.
        query_entities = _extract_query_entities(request.question)
        if query_entities:
            entity_rows = await _entity_search(
                query_entities, user_id, db, scope_type, scope_id, scope_name
            )
            if entity_rows:
                existing_ids = {chunk.id for chunk, _, _ in rows}
                added = 0
                for chunk, doc in entity_rows:
                    if chunk.id not in existing_ids:
                        # Assign high relevance — explicit entity match
                        rows.append((chunk, doc, 0.25))
                        existing_ids.add(chunk.id)
                        added += 1
                logger.info(
                    f"[RAG] Entity search: entities={query_entities}  +{added} new chunk(s)"
                )

    except Exception as exc:
        logger.error(f"[RAG] Retrieval failed: {exc}")
        yield sse("error", {"message": f"Search failed: {exc}"})
        await db.rollback()
        return

    print("Retrieval completed")
    print("Chunks found:", len(rows))

    # ── 3a. Bi-encoder pre-sort ───────────────────────────────────────────
    if rows and intent == "pageagg":
        rows = _validate_sources(rows)
        confidence_score, confidence_level = _calculate_confidence(rows)
        answer_text, citations = _format_page_aggregation_answer(rows, request.question)
        sources_data = [c.model_dump(mode="json") for c in citations]

        db.add(ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant.value,
            content=answer_text,
            sources=sources_data,
            confidence_score=confidence_score,
            response_mode=response_mode,
        ))
        try:
            await db.commit()
        except Exception:
            await db.rollback()

        yield sse("confidence", {"score": confidence_score, "level": confidence_level})
        yield sse("token", {"text": answer_text})
        yield sse("sources", {
            "sources": sources_data,
            "success": True,
            "session_id": str(session.id),
        })
        yield sse("done", {
            "session_id": str(session.id),
            "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "scope_name": scope_name,
            "response_mode": response_mode,
        })
        return
    if rows:
        rows = _rerank(rows, request.question)
        # Financial query: move chunks containing question's financial keywords
        # to the top of the candidate pool before the cross-encoder sees them.
        rows = _financial_boost(rows, request.question)

    # ── 3b. Cross-encoder rerank ──────────────────────────────────────────
    # Evaluates every (question, chunk) pair jointly — far more accurate than
    # bi-encoder cosine similarity alone, which ranks topically related but
    # non-answering chunks (e.g. "Lawsuits" in an annual report) equally high.
    # Dynamic top_k: narrow intents (fact, pageref) need 2–3 focused chunks;
    # broad intents (summary, compliance, list) need many more for coverage.
    # NOTE: do NOT cap by RERANKER_TOP_K here — that default (5) was silently
    # suppressing every broad intent's budget, which is the whole reason
    # summary/compliance/list questions ran out of evidence. The intent value
    # in _INTENT_TOP_K is the authoritative ceiling for the reranker output.
    _ce_top_k = _INTENT_TOP_K.get(intent, settings.RERANKER_TOP_K)

    # Intent-aware min_results: narrow fact intents need fewer chunks (1 correct
    # chunk is enough); broad intents (summary, comparison) need more for coverage.
    # Using a higher value here would force irrelevant chunks into focused queries.
    _INTENT_MIN_RESULTS: dict[str, int] = {
        "oneword":    1,
        "shortfact":  1,
        "numerical":  1,
        "person":     1,
        "financial":  2,
        "definition": 2,
        "process":    2,
        "arithmetic": 3,
        "compliance": 3,
        "ranking":    3,
        "comparison": 4,
        "summary":    5,
        "analytical": 4,
        "explanation":3,
    }
    _ce_min_results = _INTENT_MIN_RESULTS.get(intent, settings.RERANKER_MIN_RESULTS)

    # Intent-aware reranker input size: focused intents only need the top 10
    # candidates to find 1 correct answer; broad intents need 20 to ensure
    # full coverage before the cross-encoder makes its selection.
    _INTENT_INPUT_SIZE: dict[str, int] = {
        "oneword":    10,
        "shortfact":  10,
        "numerical":  10,
        "person":     10,
        "financial":  15,
        "definition": 12,
        "process":    12,
        "arithmetic": 20,
        "compliance": 20,
        "ranking":    20,
        "comparison": 20,
        "summary":    20,
        "analytical": 18,
        "explanation":15,
    }
    _reranker_input_size = _INTENT_INPUT_SIZE.get(intent, settings.RERANKER_INPUT_SIZE)

    if rows and settings.RERANKER_ENABLED:
        yield sse("status", {"step": "reranking", "label": "Ranking results by relevance…"})
        try:
            from app.services.reranker import rerank as _ce_rerank
            rows = await _ce_rerank(
                request.question,
                rows[:_reranker_input_size],
                top_k=_ce_top_k,
                min_score=settings.RERANKER_MIN_SCORE,
                min_results=_ce_min_results,
            )
            logger.info(
                f"[RAG] Reranker    : intent={intent}  "
                f"input_size={_reranker_input_size}  "
                f"min_results={_ce_min_results}  top_k={_ce_top_k}  "
                f"returned={len(rows)}"
            )
        except Exception as _re_exc:
            logger.warning(f"[RAG] Cross-encoder failed (using bi-encoder order): {_re_exc}")
            rows = rows[:_ce_top_k]
    elif rows:
        rows = rows[:_ce_top_k]

    # ── 3c. Parent-child context expansion (P6) ──────────────────────────
    # For each top-ranked chunk that has a section_heading, fetch adjacent
    # sibling chunks from the same section.  The LLM then sees the full
    # section context (e.g. the full product card) rather than a single row.
    if rows:
        try:
            rows = await _expand_section_context(rows, db)
        except Exception as _pce:
            logger.warning(f"[ParentChild] Expansion failed (non-fatal): {_pce}")

    # ── 3e. Low-confidence keyword fallback ──────────────────────────────
    # If the cross-encoder scored every chunk below 0.40 there may be a
    # domain/vocabulary gap (HR policy, research jargon, etc.).  Run a plain
    # ILIKE keyword search on the main query terms to surface literal matches
    # the bi-encoder may have missed due to vocabulary mismatch.
    if rows and settings.RERANKER_ENABLED:
        _max_ce = max(1.0 - float(d) for _, _, d in rows)
        if _max_ce < 0.40:
            _low_kw = [
                w.strip('?.,!;:\'"')
                for w in request.question.split()
                if len(w.strip('?.,!;:\'"')) > 3
                and w.lower().strip('?.,') not in _STOP_WORDS
            ][:5]
            if _low_kw:
                try:
                    _fb_rows = await _entity_search(
                        _low_kw, user_id, db, scope_type, scope_id, scope_name
                    )
                    if _fb_rows:
                        _existing = {chunk.id for chunk, _, _ in rows}
                        _added = 0
                        for chunk, doc in _fb_rows:
                            if chunk.id not in _existing:
                                rows.append((chunk, doc, 0.40))
                                _existing.add(chunk.id)
                                _added += 1
                        if _added:
                            rows.sort(key=lambda x: x[2])
                            rows = rows[:_ce_top_k]
                            logger.info(
                                f"[RAG] Low-conf fallback: +{_added} keyword ILIKE chunk(s)  "
                                f"(max_ce_score={_max_ce:.3f})"
                            )
                except Exception as _fb_exc:
                    logger.warning(f"[RAG] Low-conf fallback failed (non-fatal): {_fb_exc}")

    # ── 3f. Retrieval validation — cross-domain contamination filter ──────
    if rows and settings.RETRIEVAL_VALIDATION_ENABLED:
        rows, _val_issues = _validate_retrieval(rows, request.question, intent)
        if _val_issues:
            logger.warning(
                f"[RAG] Retrieval validation: {len(_val_issues)} issue(s) — "
                f"{_val_issues[:2]}"
            )

    unique_doc_ids = list({str(doc.id) for _, doc, _ in rows})
    logger.info(
        f"[RAG] Final chunks : {len(rows)} from {len(unique_doc_ids)} doc(s)  "
        f"reranker={'cross-encoder' if settings.RERANKER_ENABLED else 'bi-encoder'}  "
        f"hybrid={settings.HYBRID_SEARCH_ENABLED}"
    )
    logger.info(
        f"[RAG] {'#':>3}  {'score':>6}  {'page':>4}  "
        f"{'section':<30}  {'document':<35}  preview"
    )
    import re as _log_re
    _heading_re = _log_re.compile(r'^\[([^\]]+)\]')
    for i, (chunk, doc, dist) in enumerate(rows, 1):
        content  = chunk.content or ''
        m        = _heading_re.match(content)
        section  = (m.group(1)[:28] if m else '—')
        preview  = content.replace('\n', ' ')
        preview  = (preview[m.end():] if m else preview).strip()[:60]
        logger.info(
            f"[RAG] [{i:2d}]  {1-dist:.4f}  {str(chunk.page_number):>4}  "
            f"{section:<30}  {doc.original_name:<35}  {preview!r}"
        )

    # ── Full retrieved chunk content (INFO so always visible) ─────────────────
    _divider = "─" * 72
    logger.info(f"[RAG] {_divider}")
    logger.info(f"[RAG] RETRIEVED CHUNKS — full content ({len(rows)} total)")
    logger.info(f"[RAG] {_divider}")
    for _i, (_chunk, _doc, _dist) in enumerate(rows, 1):
        _sim    = round(1.0 - float(_dist), 4)
        _tier   = "HIGH" if _dist <= 0.25 else "MEDIUM" if _dist <= 0.45 else "LOW"
        _text   = (_chunk.content or "").strip()
        logger.info(
            f"[RAG] CHUNK [{_i}]  "
            f"sim={_sim:.4f}  tier={_tier}  "
            f"page={_chunk.page_number}  "
            f"doc={_doc.original_name!r}"
        )
        # Print full content split at newlines for readability
        for _line in _text.split("\n"):
            logger.info(f"[RAG]   │ {_line}")
        logger.info(f"[RAG] {_divider}")

    # ── Similarity score summary ───────────────────────────────────────────────
    if rows:
        _sims = [round(1.0 - float(d), 4) for _, _, d in rows]
        logger.info(
            f"[RAG] SCORES  "
            f"best={max(_sims):.4f}  "
            f"worst={min(_sims):.4f}  "
            f"avg={sum(_sims)/len(_sims):.4f}  "
            f"all={_sims}"
        )
        if settings.RETRIEVAL_DEBUG_ENABLED:
            yield sse("debug", _retrieval_debug_payload(rows))

    # ── 3b. Document disambiguation (before saving user message) ──────────
    bypass_dis = getattr(request, "bypass_disambiguation", False)
    if not bypass_dis:
        disambig_docs = _should_disambiguate(rows, scope_type, request.question)
        if disambig_docs:
            logger.info(
                f"[RAG] Disambiguation: {len(disambig_docs)} candidate document(s) "
                f"— returning clarification to user"
            )
            await db.rollback()
            yield sse("clarification", {
                "requires_domain_selection": True,
                "message": (
                    "I found this topic across multiple knowledge domains. "
                    "Please choose the domain you'd like me to answer from:"
                ),
                "domains": disambig_docs,
            })
            return

    # ── 3c. Save user message (after disambiguation — only when we will answer) ──
    try:
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.user.value,
            content=request.question,
        )
        db.add(user_msg)
        if session.title == "New Chat":
            session.title = (
                request.question[:60] + ("…" if len(request.question) > 60 else "")
            )
        await db.flush()
    except Exception as exc:
        logger.error(f"[RAG] Failed to save user message: {exc}", exc_info=True)
        yield sse("error", {"message": "Failed to save message — database error."})
        await db.rollback()
        return

    # ── 3d. Confidence score ───────────────────────────────────────────────
    confidence_score, confidence_level = _calculate_confidence(rows)
    yield sse("confidence", {"score": confidence_score, "level": confidence_level})
    logger.info(f"[RAG] Confidence  : {confidence_score}% ({confidence_level})")

    # ── 3e. Retrieval confidence gate ─────────────────────────────────────
    # Fires BEFORE the LLM call when retrieved chunks fall below relevance
    # thresholds.  Prevents hallucination on out-of-domain questions where
    # the top-K chunks are noise rather than evidence.
    # Examples caught here:
    #   "What is the CEO's favourite colour?"  — no colour policy in any doc
    #   "Maternity leave policy?"              — when no such doc is indexed
    # Examples NOT blocked (scores will be high enough):
    #   "What is the API limit for Professional plan?" — chunk directly answers
    #   "Total PTO days?"                              — multi-hop but relevant
    # Per-intent gate bypass: summary and list questions don't match topical
    # vocabulary the way "Who is the CEO?" does — the query "Summarize the
    # chapter" can have low similarity scores even when retrieval is good,
    # because the matching signal here is COVERAGE, not topical match strength.
    _coverage_intents = {"summary", "list", "pageagg"}

    # Summary fallback: if retrieval came back nearly empty for a coverage-driven
    # intent, the embedding of "Summarize the chapter" is just too generic to
    # match document vocabulary. Fall back to fetching the first N chunks of
    # the scoped document(s) by chunk_index so the LLM gets material to
    # summarize. Never refuse a summary purely because the query wording was
    # generic — that's the user's repeated complaint.
    if intent in _coverage_intents and (rows is None or len(rows) < 3):
        _target_n = _INTENT_TOP_K.get(intent, 15)
        try:
            fallback_rows = await _fetch_scope_chunks_by_order(
                user_id=user_id,
                scope_type=scope_type,
                scope_id=scope_id,
                scope_name=scope_name,
                limit=_target_n,
                db=db,
            )
            if fallback_rows:
                logger.info(
                    f"[Summary] EMPTY-RETRIEVAL FALLBACK fired — "
                    f"original_rows={0 if not rows else len(rows)}  "
                    f"fetched_by_order={len(fallback_rows)}  intent={intent}"
                )
                rows = fallback_rows
        except Exception as _fb_exc:
            logger.warning(f"[Summary] Empty-rows fallback failed: {_fb_exc}")

    _bypass_gate = (
        intent in _coverage_intents
        and rows is not None
        and len(rows) >= 3
    )

    if rows and _bypass_gate:
        logger.info(
            f"[ConfidenceGate] BYPASSED for intent={intent}  "
            f"chunks={len(rows)}  reason=coverage-driven intent"
        )

    # Master diagnostic — answers "why did this query fail" in one log line
    _sims_preview = [round(1.0 - float(d), 3) for _, _, d in rows][:10] if rows else []
    logger.info(
        f"[Trace] Stage 5 — Retrieved chunks: {len(rows) if rows else 0}  "
        f"top10_sims={_sims_preview}  "
        f"confidence={confidence_score:.1f}  "
        f"bypass_gate={_bypass_gate}"
    )

    if rows and not _bypass_gate:
        _gate_block, _gate_reason, _gate_scores = _retrieval_confidence_gate(
            rows, confidence_score
        )
        if _gate_block:
            logger.info(
                f"[ConfidenceGate] BLOCKED  reason={_gate_reason}  "
                f"scores={_gate_scores}  question={request.question!r}"
            )
            _nf_text = _not_found_gated_response(
                request.question, rows, _gate_scores, _gate_reason
            )
            db.add(ChatMessage(
                session_id=session.id,
                role=MessageRole.assistant.value,
                content=_nf_text,
                sources=[],
                confidence_score=confidence_score,
                response_mode=response_mode,
            ))
            try:
                await db.commit()
            except Exception:
                await db.rollback()
            yield sse("not_found", {
                "reason":    _gate_reason,
                "scores":    _gate_scores,
                "threshold": {
                    "absolute_min":    settings.CONFIDENCE_GATE_ABSOLUTE_MIN,
                    "score_min":       settings.CONFIDENCE_GATE_SCORE_MIN,
                    "high_quality_sim": settings.CONFIDENCE_GATE_HIGH_QUALITY_SIM,
                },
            })
            yield sse("token",   {"text": _nf_text})
            yield sse("sources", {"sources": [], "success": False,
                                  "message": _nf_text, "session_id": str(session.id)})
            yield sse("done",    {
                "session_id": str(session.id), "scope_type": scope_type,
                "scope_id": str(scope_id) if scope_id else None,
                "scope_name": scope_name, "response_mode": response_mode,
            })
            return

    # ── 4. Handle truly empty retrieval ───────────────────────────────────
    # With MAX_RETRIEVAL_DISTANCE=0.97 we only reach this branch when:
    #   (a) No documents are indexed for this user/scope at all, OR
    #   (b) Every single chunk is near-orthogonal (similarity < 0.03)
    if not rows:
        # Check whether there are any indexed documents at all
        count_stmt = (
            select(func.count(DocumentChunk.id))
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.user_id == user_id)
            .where(Document.status == DocumentStatus.indexed)
        )
        if scope_type == "folder" and scope_id:
            count_stmt = count_stmt.where(Document.folder_id == scope_id)
        elif scope_type == "document" and scope_id:
            count_stmt = count_stmt.where(Document.id == scope_id)
        elif scope_type == "domain" and scope_name:
            count_stmt = count_stmt.where(Document.domain_name == scope_name)

        indexed_count = (await db.scalar(count_stmt)) or 0

        if indexed_count == 0:
            no_results = _scoped_no_results_msg(scope_type, scope_name)
            logger.info("[RAG] No indexed documents for this scope — returning refusal.")
        else:
            no_results = "No relevant information found in uploaded documents."
            logger.info(
                f"[RAG] {indexed_count} indexed chunks exist but all are near-orthogonal — refusal."
            )

        db.add(ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant.value,
            content=no_results,
            sources=[],
            response_mode=response_mode,
        ))
        await db.commit()
        yield sse("token",   {"text": no_results})
        yield sse("sources", {"sources": [], "success": False, "message": no_results})
        yield sse("done",    {
            "session_id":    str(session.id),
            "scope_type":    scope_type,
            "scope_id":      str(scope_id) if scope_id else None,
            "scope_name":    scope_name,
            "response_mode": response_mode,
        })
        return

    # ── 4b. Conflict diagnostic (logging only — Gemini resolves conflicts) ──
    _conflict_diag = _detect_conflicts(request.question, rows, intent)
    if _conflict_diag:
        _role_tag = _conflict_diag.get("role", "unknown")
        logger.info(
            f"[RAG] Conflict candidates detected (passed to LLM for resolution)  "
            f"role={_role_tag}  "
            f"candidates={[c['value'] for c in _conflict_diag['candidates']]}  "
            f"question={request.question!r}"
        )

    # ── 5. Build context ───────────────────────────────────────────────────
    try:
        rows = _validate_sources(rows)
        context, citations = _format_context(rows)
        logger.info(
            f"[RAG] Context     : {len(context)} chars, {len(citations)} unique source(s)"
        )

        # Coverage QA log for summary/list intents — these depend on having
        # broad retrieval across the document, not a single high-similarity
        # match. Logging chunk-per-document distribution makes it obvious
        # when retrieval is too narrow.
        if intent in ('summary', 'list', 'pageagg'):
            _per_doc: dict[str, int] = {}
            _sims: list[float] = []
            for _ch, _doc, _dist in rows:
                _per_doc[_doc.original_name] = _per_doc.get(_doc.original_name, 0) + 1
                _sims.append(round(1.0 - float(_dist), 4))
            logger.info(
                f"[{intent.title()}] Final {len(rows)} chunk(s) → LLM  "
                f"docs_covered={len(_per_doc)}  "
                f"similarity_range=[{min(_sims):.3f}…{max(_sims):.3f}]  "
                f"per_doc={_per_doc}"
            )

        # Compliance-specific QA log: show how many chunks each policy/doc
        # contributed so we can confirm cross-policy retrieval worked.
        if intent == 'compliance':
            _per_doc: dict[str, int] = {}
            _per_cat: dict[str, int] = {}
            for _ch, _doc, _ in rows:
                _per_doc[_doc.original_name] = _per_doc.get(_doc.original_name, 0) + 1
                _cat = (getattr(_ch, "category", None)
                        or getattr(_doc, "domain_name", None)
                        or "General")
                _per_cat[_cat] = _per_cat.get(_cat, 0) + 1
            logger.info(f"[Compliance] Chunks per document : {_per_doc}")
            logger.info(f"[Compliance] Chunks per category : {_per_cat}")
            logger.info(
                f"[Compliance] Final {len(rows)} chunk(s) → LLM; "
                f"{len(_per_doc)} document(s) covered"
            )

        # ── Full context block ─────────────────────────────────────────────
        _ctx_divider = "═" * 72
        logger.info(f"[RAG] {_ctx_divider}")
        logger.info("[RAG] CONTEXT BLOCK — exact text sent to Gemini")
        logger.info(f"[RAG] {_ctx_divider}")
        for _ctx_line in context.split("\n"):
            logger.info(f"[RAG] CTX │ {_ctx_line}")
        logger.info(f"[RAG] {_ctx_divider}")
        logger.info(
            f"[RAG] CONTEXT STATS  "
            f"total_chars={len(context)}  "
            f"citations={len(citations)}  "
            f"approx_tokens={len(context)//4}"
        )
    except Exception as exc:
        logger.error(f"[RAG] Context formatting failed: {exc}", exc_info=True)
        yield sse("error", {"message": "Failed to format document context."})
        await db.rollback()
        return

    # ── 5b. Build conversation history ────────────────────────────────────
    try:
        conversation_history = await _build_conversation_context(
            session.id, user_msg.created_at or datetime.now(timezone.utc), db
        )
        logger.info(f"[RAG] History     : {len(conversation_history)} prior turn(s)")
    except Exception as exc:
        logger.warning(f"[RAG] History load failed (non-fatal): {exc}")
        conversation_history = []

    yield sse("status", {"step": "generating", "label": "Generating your answer…"})
    print("Calling LLM")

    # ── 6. Stream LLM — ordered failover chain ────────────────────────────
    # Chain order: primary → openai → anthropic → local (skips unconfigured
    # and currently-unhealthy entries).  All providers are tried before we
    # fall back to the local chunk-display path.
    _provider_chain = get_ordered_provider_chain()

    if not _provider_chain:
        # No configured or healthy provider available right now
        _no_chain_reason = _error_type_to_message("not_configured")
        logger.error(
            "[RAG] No AI providers available — chain is empty. "
            "Set GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or LOCAL_MODEL_ENDPOINT "
            "in backend/.env and restart the server."
        )
        record_llm_failure("none", "not_configured", "No providers configured")
        logger.error("[LLM] Request not sent: no configured healthy providers")
        _local_text = _local_answer_from_chunks(
            request.question, rows, error_reason=_no_chain_reason
        )
        yield sse("provider_warning", {
            "degraded": True,
            "message": "AI answer synthesis is temporarily unavailable.",
            "error_type": "not_configured",
        })
        yield sse("token", {"text": _local_text})
        sources_data = [c.model_dump(mode="json") for c in citations if citations]
        db.add(ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant.value,
            content=_local_text,
            sources=sources_data,
            confidence_score=confidence_score,
            response_mode=response_mode,
        ))
        try:
            await db.commit()
        except Exception:
            await db.rollback()
        yield sse("sources", {"sources": sources_data, "success": False, "session_id": str(session.id)})
        yield sse("done", {
            "session_id": str(session.id), "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None, "scope_name": scope_name,
            "response_mode": response_mode,
        })
        return

    _active_provider_name, ai_provider = _provider_chain[0]
    _remaining_chain = _provider_chain[1:]

    # Notify if we're already on a fallback (primary was unhealthy)
    if _active_provider_name != settings.AI_PROVIDER:
        _ph = get_provider_health(settings.AI_PROVIDER)
        logger.info(
            f"[RAG] Primary {settings.AI_PROVIDER} unhealthy "
            f"(error_type={_ph.get('error_type')}) — using {_active_provider_name}"
        )
        yield sse("provider_warning", {
            "degraded": True,
            "message": (
                f"Primary AI provider ({settings.AI_PROVIDER}) is temporarily "
                f"unavailable. Using {_active_provider_name}."
            ),
            "error_type": _ph.get("error_type"),
        })
    full_response = ""
    complexity = _detect_question_complexity(request.question)
    system_prompt = _build_system_prompt(
        scope_type, scope_name, mode=response_mode, complexity=complexity, intent=intent
    )
    logger.info(f"[RAG] Complexity  : {complexity}  intent={intent}")
    logger.info(
        f"[RAG] LLM provider: {_active_provider_name}"
    )
    logger.info(
        "[LLM] Request sent to %s model=%s input_chars=%s context_chars=%s chunks=%s",
        _active_provider_name,
        getattr(ai_provider, "_model", "unknown"),
        len(system_prompt) + len(context) + len(request.question),
        len(context),
        len(rows),
    )

    # ── Full system prompt ─────────────────────────────────────────────────
    _prompt_divider = "▸" * 72
    logger.info(f"[RAG] {_prompt_divider}")
    logger.info(
        f"[RAG] SYSTEM PROMPT  "
        f"chars={len(system_prompt)}  "
        f"approx_tokens={len(system_prompt)//4}  "
        f"intent={intent}  complexity={complexity}  mode={response_mode}"
    )
    logger.info(f"[RAG] {_prompt_divider}")
    for _sp_line in system_prompt.split("\n"):
        logger.info(f"[RAG] SYS │ {_sp_line}")
    logger.info(f"[RAG] {_prompt_divider}")

    # ── Context size validation ─────────────────────────────────────────────
    # Gemini 2.5 Flash and gpt-4o-mini both accept ~1M / 128K tokens, but we
    # cap defensively to avoid edge-case provider failures on huge summaries.
    _MAX_CONTEXT_CHARS = 600_000  # ~150K tokens at ~4 chars/token
    if len(context) > _MAX_CONTEXT_CHARS:
        logger.warning(
            f"[RAG] Context too large ({len(context)} chars) — trimming to "
            f"{_MAX_CONTEXT_CHARS} chars before LLM call. "
            f"Consider reducing TOP_K for this intent={intent}."
        )
        context = context[:_MAX_CONTEXT_CHARS]
    _total_prompt_chars = len(system_prompt) + len(context) + len(request.question)
    logger.info(
        f"[Trace] Stage 6 — Prompt size: system={len(system_prompt)} chars  "
        f"context={len(context)} chars  question={len(request.question)} chars  "
        f"total={_total_prompt_chars} chars  ~tokens={_total_prompt_chars // 4}"
    )

    _llm_t_start = _time.monotonic()
    try:
        _llm_started = False
        async for token in ai_provider.stream_chat(
            system_prompt,
            request.question,
            context,
            conversation_history=conversation_history,
        ):
            if not _llm_started:
                print("LLM response started")
                _llm_started = True
            print("Streaming token:", token)
            full_response += token
            yield sse("token", {"text": token})

        # Provider responded successfully — clear any previous failure record
        mark_provider_healthy(_active_provider_name)

        # ── Full response logging ──────────────────────────────────────────
        _llm_ms = round((_time.monotonic() - _llm_t_start) * 1000)
        _input_chars = len(system_prompt) + len(context) + len(request.question)
        record_llm_success(
            provider=_active_provider_name,
            model=getattr(ai_provider, "_model", "unknown"),
            input_chars=_input_chars,
            response_chars=len(full_response),
            elapsed_ms=_llm_ms,
        )
        logger.info(
            "[LLM] Response received provider=%s model=%s latency_ms=%s chars=%s",
            _active_provider_name,
            getattr(ai_provider, "_model", "unknown"),
            _llm_ms,
            len(full_response),
        )
        logger.info(
            f"[RAG] ✓ LLM SUCCESS  "
            f"provider={_active_provider_name}  "
            f"query={request.question[:60]!r}  "
            f"chunks={len(rows)}  "
            f"context={len(context)} chars (~{len(context)//4} tokens)  "
            f"response={len(full_response)} chars (~{len(full_response)//4} tokens)  "
            f"time={_llm_ms}ms"
        )
        _resp_divider = "◀" * 72
        logger.info(f"[RAG] {_resp_divider}")
        logger.info(
            f"[RAG] LLM RESPONSE  "
            f"provider={_active_provider_name}  "
            f"chars={len(full_response)}  "
            f"approx_tokens={len(full_response)//4}  "
            f"time={_llm_ms}ms"
        )
        logger.info(f"[RAG] {_resp_divider}")
        for _resp_line in full_response.split("\n"):
            logger.info(f"[RAG] RSP │ {_resp_line}")
        logger.info(f"[RAG] {_resp_divider}")

        # ── Empty response guard ───────────────────────────────────────────
        if not full_response.strip():
            logger.warning(
                "[RAG] ⚠ Gemini returned an empty response — "
                "check GEMINI_API_KEY, quota, and model availability."
            )
            fallback_text = (
                "**The AI model returned an empty response.**\n\n"
                "**Possible causes:**\n"
                "- The request was blocked by a Gemini safety filter\n"
                "- The API key is invalid or has expired\n"
                "- The model (`GEMINI_MODEL` in `backend/.env`) is unavailable\n\n"
                "**To fix:** Check `GEMINI_API_KEY` in `backend/.env` and review server logs."
            )
            yield sse("token", {"text": fallback_text})
            full_response = fallback_text

        # ── Refusal detection ──────────────────────────────────────────────
        _refusal_phrases = (
            "not available in the uploaded documents",
            "not found in documents",
            "i could not find",
            "could not find a specific answer",
        )
        if any(phrase in full_response.lower() for phrase in _refusal_phrases):
            logger.warning(f"[RAG] {_resp_divider}")
            logger.warning("[RAG] ⚠ REFUSAL TRIGGERED — Gemini returned refusal string")
            logger.warning(f"[RAG]   Question : {request.question!r}")
            logger.warning(
                f"[RAG]   Context  : {len(context)} chars  "
                f"chunks={len(rows)}  "
                f"best_sim={max((round(1-float(d),4) for _,_,d in rows), default=0)}"
            )
            logger.warning(
                "[RAG]   Diagnosis: Gemini received context but decided it "
                "does not answer the question. Possible causes: "
                "(1) CEO name and title in separate chunks — now fixed by RULE 4, "
                "(2) chunk is LOW relevance tier, "
                "(3) context vocabulary differs from question vocabulary."
            )
            logger.warning(f"[RAG] {_resp_divider}")

    except (GeneratorExit, asyncio.CancelledError, ConnectionResetError):
        logger.warning("[RAG] Stream cancelled by client while LLM was generating")
        raise
    except TimeoutError as exc:
        logger.error(f"[RAG] LLM timeout: {exc}", exc_info=True)
        exc = AIServiceUnavailableError(str(exc), error_type="unavailable")
        error_type = getattr(exc, "error_type", "unavailable")
        record_llm_failure(_active_provider_name, error_type, str(exc))
        mark_provider_failed(_active_provider_name, error_type)
        logger.error(
            "[LLM] Request failed provider=%s error_type=%s detail=%s",
            _active_provider_name,
            error_type,
            exc,
        )
        full_text = _local_answer_from_chunks(
            request.question,
            rows,
            error_reason=_error_type_to_message(error_type, _active_provider_name),
        )
        yield sse("provider_warning", {
            "degraded": True,
            "message": f"{_active_provider_name} timed out. Returning retrieved context instead.",
            "error_type": error_type,
        })
        yield sse("token", {"text": full_text})
        sources_data = [c.model_dump(mode="json") for c in citations if citations]
        yield sse("sources", {
            "sources": sources_data,
            "success": False,
            "error_type": error_type,
            "session_id": str(session.id),
        })
        yield sse("done", {
            "session_id": str(session.id),
            "scope_type": scope_type,
            "scope_id": str(scope_id) if scope_id else None,
            "scope_name": scope_name,
            "response_mode": response_mode,
        })
        print("Stream completed")
        return
    except Exception as exc:
        # Catch both AIServiceUnavailableError and any unexpected exception
        # (e.g. a raw SDK error that slipped through a provider's exception handler).
        if not isinstance(exc, AIServiceUnavailableError):
            logger.error(
                f"[RAG] Unexpected exception from provider {_active_provider_name} — "
                f"{type(exc).__name__}: {exc}",
                exc_info=True,
            )
            exc = AIServiceUnavailableError(str(exc), error_type="unavailable")
        error_type = getattr(exc, "error_type", "unavailable")
        logger.error(
            f"[RAG] ✗ LLM FAILURE  "
            f"provider={_active_provider_name}  "
            f"error_type={error_type}  "
            f"query={request.question[:60]!r}  "
            f"chunks={len(rows)}  "
            f"context={len(context)} chars  "
            f"detail={exc}",
            exc_info=False,
        )
        record_llm_failure(_active_provider_name, error_type, str(exc))
        mark_provider_failed(_active_provider_name, error_type)

        # ── Walk the remaining chain until one succeeds ────────────────────
        full_text      = ""
        _used_failover = False

        for _fb_name, _fb_provider in _remaining_chain:
            logger.info(f"[RAG] Failover: trying {_fb_name}")
            yield sse("provider_warning", {
                "degraded": True,
                "message": (
                    f"{_active_provider_name} is unavailable "
                    f"({'quota exceeded' if error_type == 'quota_exceeded' else 'service down'}). "
                    f"Switched to {_fb_name}."
                ),
                "error_type": error_type,
            })
            try:
                async for _fb_token in _fb_provider.stream_chat(
                    system_prompt,
                    request.question,
                    context,
                    conversation_history=conversation_history,
                ):
                    full_text += _fb_token
                    yield sse("token", {"text": _fb_token})
                _used_failover = True
                mark_provider_healthy(_fb_name)
                logger.info(f"[RAG] Failover to {_fb_name} succeeded ({len(full_text)} chars)")
                break
            except Exception as _fb_exc:
                logger.error(f"[RAG] Failover provider {_fb_name} also failed: {_fb_exc}")
                mark_provider_failed(_fb_name, "unavailable")

        if not _used_failover:
            # All providers exhausted — show intelligent local answer
            _exhausted_reason = _error_type_to_message(error_type, _active_provider_name)
            _providers_tried   = [_active_provider_name] + [n for n, _ in _remaining_chain]
            logger.error(
                f"[RAG] ✗ ALL PROVIDERS EXHAUSTED — "
                f"tried={_providers_tried}  error_type={error_type}  "
                f"falling back to local chunk display"
            )
            full_text = _local_answer_from_chunks(
                request.question, rows, error_reason=_exhausted_reason
            )
            yield sse("provider_warning", {
                "degraded":    True,
                "message":     f"All AI providers are temporarily unavailable. {_exhausted_reason}",
                "error_type":  error_type,
                "providers_tried": _providers_tried,
                "fix": (
                    "Check GET /api/v1/debug/provider-health for per-provider status "
                    "and fix instructions."
                ),
            })
            yield sse("token", {"text": full_text})

        sources_data = [c.model_dump(mode="json") for c in citations if citations]
        db.add(ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant.value,
            content=full_text,
            sources=sources_data,
            confidence_score=confidence_score,
            response_mode=response_mode,
        ))
        try:
            await db.commit()
        except Exception:
            await db.rollback()

        yield sse("sources", {
            "sources":    sources_data,
            "success":    _used_failover,
            "error_type": error_type,
            "session_id": str(session.id),
        })
        yield sse("done", {
            "session_id":    str(session.id),
            "scope_type":    scope_type,
            "scope_id":      str(scope_id) if scope_id else None,
            "scope_name":    scope_name,
            "response_mode": response_mode,
        })
        return

    logger.info(f"[RAG] Response    : {len(full_response)} chars")
    logger.info(f"[RAG] ✓ LLM SUCCESS — streaming {len(full_response)} chars to client")
    logger.info(divider)

    # ── 6b. Analyse response → metadata SSE event ─────────────────────────
    try:
        metadata = analyze_response(request.question, full_response)
        yield sse("metadata", metadata)
        logger.info(f"[RAG] Response type: {metadata.get('response_type', 'text')}")
    except Exception as exc:
        logger.warning(f"[RAG] Response analysis failed (non-fatal): {exc}")

    # ── 7. Persist assistant message ───────────────────────────────────────
    try:
        sources_data = [c.model_dump(mode="json") for c in citations]
        db.add(
            ChatMessage(
                session_id=session.id,
                role=MessageRole.assistant.value,
                content=full_response,
                sources=sources_data,
                confidence_score=confidence_score,
                response_mode=response_mode,
            )
        )
        await db.commit()
    except Exception as exc:
        logger.error(f"[RAG] Failed to persist assistant message: {exc}", exc_info=True)
        sources_data = []
        try:
            await db.rollback()
        except Exception:
            pass

    # ── 8. Send sources + done events ──────────────────────────────────────
    yield sse("sources", {
        "sources":    sources_data,
        "success":    True,
        "session_id": str(session.id),
    })
    yield sse("done", {
        "session_id":    str(session.id),
        "scope_type":    scope_type,
        "scope_id":      str(scope_id) if scope_id else None,
        "scope_name":    scope_name,
        "response_mode": response_mode,
    })
    logger.info(f"[RAG] ✓ RESPONSE DELIVERED — session={session.id}")
    print("Stream completed")

    # ── 9. Save query analytics (best-effort, non-blocking) ─────────────────
    try:
        elapsed_ms = int((_time.monotonic() - _t_start) * 1000)
        entities   = _extract_query_entities(request.question) or None
        _rows_ref  = rows if "rows" in dir() else []  # guard: rows may not be set on early paths
        top_5      = [
            {
                "chunk_id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "doc_name": doc.original_name,
                "source_document": getattr(chunk, "source_document", None) or doc.original_name,
                "page":     chunk.page_number,
                "section": getattr(chunk, "section_heading", None),
                "dist":     round(float(dist), 4),
                "sim":      round(1.0 - float(dist), 4),
                "embedding_model": getattr(chunk, "embedding_model", None),
                "embedding_version": getattr(chunk, "embedding_version", None),
            }
            for chunk, doc, dist in _rows_ref[:5]
        ] if _rows_ref else None
        db.add(QueryAnalytics(
            user_id          = user_id,
            session_id       = session.id,
            original_query   = request.question,
            expanded_query   = embed_query if embed_query != request.question else None,
            response_mode    = response_mode,
            scope_type       = scope_type,
            chunks_retrieved = len(_rows_ref),
            docs_searched    = len({str(doc.id) for _, doc, _ in _rows_ref}),
            confidence_score = confidence_score,
            response_time_ms = elapsed_ms,
            entities_extracted = entities,
            top_chunks       = top_5,
            used_pgvector    = "yes" if _pv.is_available() else "no",
        ))
        await db.commit()
        logger.debug(f"[RAG] Analytics saved ({elapsed_ms} ms)")
    except Exception as _ae:
        logger.debug(f"[RAG] Analytics save skipped: {_ae}")


# ─────────────────────────────────────────────────────────────────────────────
# Session / history helpers
# ─────────────────────────────────────────────────────────────────────────────

async def list_sessions(
    user_id: uuid.UUID, db: AsyncSession
) -> list[ChatSessionResponse]:
    # ── Step 1: fetch sessions with message count ──────────────────────────
    stmt = (
        select(ChatSession, func.count(ChatMessage.id).label("msg_count"))
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .group_by(ChatSession)
        .order_by(ChatSession.pinned.desc(), ChatSession.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    # ── Step 2: fetch the last assistant message per session ──────────────
    session_ids = [s.id for s, _ in rows]
    preview_map: dict[str, str] = {}
    try:
        for sid in session_ids:
            msg_stmt = (
                select(ChatMessage.content)
                .where(ChatMessage.session_id == sid)
                .where(ChatMessage.role == MessageRole.assistant.value)
                .order_by(ChatMessage.created_at.desc())
                .limit(1)
            )
            result = await db.scalar(msg_stmt)
            if result:
                raw = result.strip().replace("\n", " ")
                preview_map[str(sid)] = raw[:120] + ("…" if len(raw) > 120 else "")
    except Exception:
        pass  # preview is optional — never break session listing

    return [
        ChatSessionResponse(
            id=s.id,
            title=s.title,
            scope_type=s.scope_type,
            scope_id=s.scope_id,
            scope_name=s.scope_name,
            pinned=s.pinned,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=cnt,
            last_message_preview=preview_map.get(str(s.id)),
        )
        for s, cnt in rows
    ]


async def get_session_messages(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[ChatMessageResponse]:
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    msgs = (await db.execute(stmt)).scalars().all()
    return [
        ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=[SourceCitation(**s) for s in (m.sources or [])],
            confidence_score=m.confidence_score,
            response_mode=m.response_mode,
            created_at=m.created_at,
        )
        for m in msgs
    ]


async def delete_session(
    session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
):
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")
    await db.delete(session)
    await db.commit()


async def rename_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    db: AsyncSession,
) -> ChatSessionResponse:
    """Update the title of a chat session."""
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")

    session.title = title.strip()[:500]
    await db.commit()
    await db.refresh(session)

    msg_count = await db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        scope_type=session.scope_type,
        scope_id=session.scope_id,
        scope_name=session.scope_name,
        pinned=session.pinned,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=msg_count or 0,
    )


async def toggle_pin_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> ChatSessionResponse:
    """Toggle the pinned state of a chat session."""
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")

    session.pinned = not session.pinned
    await db.commit()
    await db.refresh(session)

    msg_count = await db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        scope_type=session.scope_type,
        scope_id=session.scope_id,
        scope_name=session.scope_name,
        pinned=session.pinned,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=msg_count or 0,
    )


async def update_session(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str | None,
    pinned: bool | None,
    db: AsyncSession,
) -> ChatSessionResponse:
    """Update title and/or pinned state of a session (PATCH semantics)."""
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")

    if title is not None:
        session.title = title.strip()[:500]
    if pinned is not None:
        session.pinned = pinned

    await db.commit()
    await db.refresh(session)

    msg_count = await db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.session_id == session_id)
    )
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        scope_type=session.scope_type,
        scope_id=session.scope_id,
        scope_name=session.scope_name,
        pinned=session.pinned,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=msg_count or 0,
    )


async def submit_feedback(
    message_id: uuid.UUID,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: str,
    db: AsyncSession,
) -> FeedbackResponse:
    """
    Upsert feedback for a message.
    Deletes any existing feedback for the same message_id before inserting new.
    This allows users to change their rating.
    """
    # Verify the message exists and belongs to the user's session
    msg = await db.get(ChatMessage, message_id)
    if not msg:
        raise NotFoundError("Message")
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        raise NotFoundError("Chat session")
    if msg.session_id != session_id:
        raise NotFoundError("Message")

    # Delete any existing feedback for this message by this user
    await db.execute(
        delete(MessageFeedback)
        .where(MessageFeedback.message_id == message_id)
        .where(MessageFeedback.user_id == user_id)
    )

    # Insert new feedback
    feedback = MessageFeedback(
        message_id=message_id,
        session_id=session_id,
        user_id=user_id,
        rating=rating,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(
        id=feedback.id,
        message_id=feedback.message_id,
        rating=feedback.rating,
        created_at=feedback.created_at,
    )


async def regenerate_response(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """
    Regenerate the last assistant response in a session.

    Steps:
    1. Find the last assistant message in the session.
    2. Find the last user message before it.
    3. Delete the assistant message.
    4. Re-run stream_query with the same question and session scope.
    5. Yield all SSE events from stream_query.
    """

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    # Verify session ownership
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        yield sse("error", {"message": "Chat session not found."})
        return

    # Find last assistant message
    last_assistant_stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == MessageRole.assistant.value)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    last_assistant = (await db.execute(last_assistant_stmt)).scalar_one_or_none()
    if not last_assistant:
        yield sse("error", {"message": "No assistant message found to regenerate."})
        return

    # Find the last user message before the assistant message
    last_user_stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == MessageRole.user.value)
        .where(ChatMessage.created_at < last_assistant.created_at)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    last_user = (await db.execute(last_user_stmt)).scalar_one_or_none()
    if not last_user:
        yield sse("error", {"message": "No user message found to regenerate from."})
        return

    original_question = last_user.content
    original_mode     = last_assistant.response_mode or "auto"

    # Delete the old assistant message
    await db.delete(last_assistant)
    await db.commit()

    # Also delete the old user message so stream_query can re-save it cleanly
    await db.delete(last_user)
    await db.commit()

    # Build a new ChatQueryRequest reusing the session scope
    regen_request = ChatQueryRequest(
        question=original_question,
        session_id=session_id,
        scope_type=session.scope_type,
        scope_id=session.scope_id,
        scope_name=session.scope_name,
        response_mode=original_mode,
    )

    # Stream the regenerated response
    async for event in stream_query(regen_request, user_id, db):
        yield event


async def get_recent_queries(
    user_id: uuid.UUID, db: AsyncSession, limit: int = 10
) -> list[RecentQueryResponse]:
    import re as _re

    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == user_id)
        .where(ChatMessage.role == MessageRole.user.value)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    msgs = (await db.execute(stmt)).scalars().all()

    result: list[RecentQueryResponse] = []
    for m in msgs:
        # Fetch the next assistant reply in the same session
        answer_stmt = (
            select(ChatMessage.content)
            .where(ChatMessage.session_id == m.session_id)
            .where(ChatMessage.role == MessageRole.assistant.value)
            .where(ChatMessage.created_at > m.created_at)
            .order_by(ChatMessage.created_at.asc())
            .limit(1)
        )
        raw_answer: str | None = (await db.execute(answer_stmt)).scalar_one_or_none()

        answer_preview: str | None = None
        if raw_answer:
            # Strip common markdown so the preview reads as plain text
            clean = _re.sub(r'\*\*|__|[#*`~]', '', raw_answer)
            clean = _re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)
            clean = _re.sub(r'\s+', ' ', clean).strip()
            answer_preview = (clean[:120] + "…") if len(clean) > 120 else clean

        result.append(
            RecentQueryResponse(
                id=m.id,
                session_id=m.session_id,
                question=m.content,
                sources=[SourceCitation(**s) for s in (m.sources or [])],
                created_at=m.created_at,
                answer_preview=answer_preview,
            )
        )
    return result
