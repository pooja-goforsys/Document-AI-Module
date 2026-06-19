"""
Retrieval and answer generation unit tests.

Covers 10 question types:
  1. One-word questions
  2. One-line (short) questions
  3. Definition questions
  4. Fact questions (numbers, dates)
  5. Multi-page / comprehensive questions
  6. Follow-up / conversation questions
  7. Synonym-based questions
  8. Misspelled questions
  9. Ambiguous questions
 10. No-result / out-of-scope questions

Run with:
    cd backend
    pytest tests/test_retrieval.py -v
"""
import types
import uuid
import pytest

from app.services.chat_service import (
    _detect_question_complexity,
    _intent_classify,
    _expand_query,
    _has_pronoun_reference,
    _needs_ambiguity_clarification,
    _extract_history_context_terms,
    _extract_query_entities,
    _contextualize_query,
    _rerank,
    _rrf_fuse_results,
    _metadata_filter_rows,
    _format_page_aggregation_answer,
    _build_direct_excerpt,  # noqa: F401 — tested in TestBuildDirectExcerpt
    NO_RELEVANT_MSG,
)
from app.services.retrieval_metadata import infer_chunk_category, infer_query_categories


# ─── Helpers to build fake chunk/doc/dist tuples ──────────────────────────────

def _make_chunk(content: str, page: int | None = 1) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        content=content,
        page_number=page,
        embedding=[0.0] * 768,
    )


def _make_doc(name: str = "sample.pdf") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        original_name=name,
        domain_name=None,
    )


def _row(content: str, dist: float = 0.2, doc_name: str = "doc.pdf") -> tuple:
    return (_make_chunk(content), _make_doc(doc_name), dist)


# ─── _detect_question_complexity ─────────────────────────────────────────────

class TestDetectQuestionComplexity:

    # 1. One-word questions → "fact"
    def test_one_word(self):
        assert _detect_question_complexity("Revenue") == "fact"
        assert _detect_question_complexity("Author") == "fact"

    # 2. Short factual questions → "fact"
    def test_who_when_fact(self):
        assert _detect_question_complexity("Who wrote this document?") == "fact"
        assert _detect_question_complexity("When was this published?") == "fact"
        assert _detect_question_complexity("How many users are there?") == "fact"
        assert _detect_question_complexity("What year was this released?") == "fact"

    # 3. Definition questions → "definition"
    def test_definition(self):
        assert _detect_question_complexity("What is RAG?") == "definition"
        assert _detect_question_complexity("What are embeddings?") == "definition"
        assert _detect_question_complexity("Define GDPR") == "definition"
        assert _detect_question_complexity("Who is the CEO?") == "definition"

    # 4. Short non-definition questions → "short"
    def test_short(self):
        assert _detect_question_complexity("List the features") == "short"

    # 5. Multi-page / comprehensive questions → "detailed"
    def test_detailed(self):
        assert _detect_question_complexity("Explain the entire authentication flow in detail") == "detailed"
        assert _detect_question_complexity("Compare JWT and session-based auth") == "detailed"

    # 6. Medium questions
    def test_medium(self):
        result = _detect_question_complexity("What are the main advantages of this system?")
        assert result in ("medium", "definition")

    # 7. Follow-up short question
    def test_followup(self):
        assert _detect_question_complexity("Why?") == "fact"
        assert _detect_question_complexity("How?") == "fact"


# ─── _expand_query ────────────────────────────────────────────────────────────

class TestExpandQuery:

    # 8. Long query — original is always preserved as the first component
    def test_long_query_includes_original(self):
        q = "Explain the difference between synchronous and asynchronous processing in detail"
        result = _expand_query(q)
        assert result.startswith(q)

    # 1. One-word query — expanded
    def test_one_word_expanded(self):
        result = _expand_query("revenue")
        assert "revenue" in result
        assert len(result) > len("revenue")

    # 2. Short question with opener — expanded
    def test_short_with_opener_expanded(self):
        result = _expand_query("what is pgvector")
        assert "pgvector" in result
        assert len(result.split()) > 3

    # 9. Ambiguous / vague queries — expanded
    def test_ambiguous_term_expanded(self):
        result = _expand_query("settings")
        assert "settings" in result
        assert "what is settings" in result or "explain settings" in result

    def test_vacation_rollover_expands_to_pto_carry_forward(self):
        result = _expand_query("Can vacation days roll over?")
        result_lower = result.lower()

        assert "pto" in result_lower
        assert "paid time off" in result_lower
        assert "leave carry forward" in result_lower


# ─── _rerank ──────────────────────────────────────────────────────────────────

class TestRerank:

    def test_empty_returns_empty(self):
        assert _rerank([], "anything") == []

    def test_no_q_words_unchanged(self):
        rows = [_row("hello world", 0.3), _row("foo bar", 0.5)]
        # Question with only stopwords — ranking may change but shouldn't crash
        result = _rerank(rows, "the a an")
        assert len(result) == 2

    # Keyword-matching chunk should rank higher than non-matching
    def test_keyword_match_ranks_higher(self):
        high_dist_but_keyword = _row("The authentication token expires after 24 hours", dist=0.50)
        low_dist_no_keyword   = _row("unrelated content about apples and oranges", dist=0.20)
        rows = [low_dist_no_keyword, high_dist_but_keyword]
        result = _rerank(rows, "authentication token expiry")
        # The keyword-matching chunk should end up first (lower combined distance)
        assert "authentication" in result[0][0].content.lower()

    # Re-ranking preserves all rows
    def test_preserves_all_rows(self):
        rows = [_row(f"content {i}", dist=0.1 * i) for i in range(1, 6)]
        result = _rerank(rows, "content")
        assert len(result) == 5

    # Output is sorted by combined distance ascending
    def test_sorted_ascending(self):
        rows = [_row("content alpha beta", dist=0.6), _row("content alpha", dist=0.1)]
        result = _rerank(rows, "alpha beta")
        assert result[0][2] <= result[1][2]


# ─── _build_direct_excerpt ────────────────────────────────────────────────────

class TestPageAggregation:

    def test_which_pages_contain_is_pageagg_intent(self):
        assert _intent_classify("Which pages contain PTO information?") == "pageagg"

    def test_page_aggregation_lists_all_unique_pages(self):
        doc = _make_doc("handbook.pdf")
        rows = [
            (_make_chunk("PTO policy overview", page=5), doc, 0.10),
            (_make_chunk("PTO carry forward rules", page=20), doc, 0.20),
            (_make_chunk("Paid time off examples", page=30), doc, 0.30),
            (_make_chunk("Duplicate PTO mention", page=5), doc, 0.40),
        ]

        answer, citations = _format_page_aggregation_answer(
            rows,
            "Which pages contain PTO information?",
        )

        assert "5, 20, 30" in answer
        assert len(citations) == 3
        assert [c.page_number for c in citations] == [5, 20, 30]

class TestMetadataFiltering:

    def test_infers_travel_and_expense_categories(self):
        assert infer_chunk_category("Travel Policy", "Flights and hotel reimbursement") == "Travel"
        assert infer_chunk_category("Expense Submission", "Submit receipts for reimbursement") == "Expense"

    def test_travel_query_prefers_travel_and_expense(self):
        categories = infer_query_categories("What is the travel reimbursement policy?")
        assert categories == {"Travel", "Expense"}

    def test_metadata_filter_removes_leave_and_benefits_for_travel(self):
        doc = _make_doc()
        travel = _make_chunk("Travel Policy: flights and hotels")
        travel.category = "Travel"
        expense = _make_chunk("Expense Submission: receipts for travel reimbursement")
        expense.category = "Expense"
        leave = _make_chunk("PTO Policy: vacation days")
        leave.category = "Leave"
        benefits = _make_chunk("Benefits: wellness allowance")
        benefits.category = "Benefits"

        rows = [
            (leave, doc, 0.10),
            (benefits, doc, 0.12),
            (travel, doc, 0.20),
            (expense, doc, 0.25),
        ]

        filtered, stats = _metadata_filter_rows(
            rows,
            "What is the travel reimbursement policy?",
            min_results=2,
        )

        assert stats["enabled"] is True
        assert {row[0].category for row in filtered} == {"Travel", "Expense"}

class TestRrfFusion:

    def test_overlap_ranks_first(self):
        doc = _make_doc()
        overlap = _make_chunk("CEO: Jane Doe")
        vector_only = _make_chunk("leadership overview")
        keyword_only = _make_chunk("Chief Executive Officer Jane Doe")

        vector_rows = [
            (vector_only, doc, 0.10),
            (overlap, doc, 0.60),
        ]
        keyword_rows = [
            (overlap, doc),
            (keyword_only, doc),
        ]

        fused, stats = _rrf_fuse_results(vector_rows, keyword_rows, rrf_k=60)

        assert fused[0][0].id == overlap.id
        assert stats["overlap"] == 1
        assert stats["keyword_only"] == 1

    def test_keyword_only_is_preserved(self):
        doc = _make_doc()
        vector_chunk = _make_chunk("semantic result")
        keyword_chunk = _make_chunk("VPN exact acronym result")

        fused, stats = _rrf_fuse_results(
            [(vector_chunk, doc, 0.20)],
            [(keyword_chunk, doc)],
            rrf_k=60,
        )

        assert {row[0].id for row in fused} == {vector_chunk.id, keyword_chunk.id}
        assert stats["keyword_only"] == 1

class TestBuildDirectExcerpt:

    # 10. Empty → no-result message
    def test_empty_returns_no_result(self):
        assert _build_direct_excerpt([]) == NO_RELEVANT_MSG

    # Returns at most 3 excerpts
    def test_max_three_excerpts(self):
        rows = [_row(f"chunk content {i}", doc_name=f"doc{i}.pdf") for i in range(6)]
        result = _build_direct_excerpt(rows)
        # Only [1], [2], [3] should appear
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result
        assert "[4]" not in result

    def test_includes_document_name(self):
        rows = [_row("important fact about X", doc_name="annual_report.pdf")]
        result = _build_direct_excerpt(rows)
        assert "annual_report.pdf" in result

    def test_includes_fallback_note(self):
        rows = [_row("some content")]
        result = _build_direct_excerpt(rows)
        assert "temporarily unavailable" in result.lower() or "unavailable" in result.lower()

    def test_truncates_long_content(self):
        long_content = "A" * 2000
        rows = [_row(long_content)]
        result = _build_direct_excerpt(rows)
        # Should be truncated to ≤ 600 chars for the excerpt body
        assert len(result) < 2000


# ─── _has_pronoun_reference ───────────────────────────────────────────────────

class TestHasPronounReference:

    # 6. Follow-up questions — pronouns detected
    def test_it_pronoun(self):
        assert _has_pronoun_reference("Who founded it?") is True
        assert _has_pronoun_reference("What is its revenue?") is True

    def test_they_pronoun(self):
        assert _has_pronoun_reference("How do they work?") is True

    def test_this_that_pronouns(self):
        assert _has_pronoun_reference("Explain this further.") is True
        assert _has_pronoun_reference("What does that mean?") is True

    def test_the_company_phrase(self):
        assert _has_pronoun_reference("When was the company founded?") is True
        assert _has_pronoun_reference("What does the platform do?") is True

    # Self-contained questions — no pronoun reference
    def test_no_pronoun_standalone(self):
        assert _has_pronoun_reference("What is BookWrench?") is False
        assert _has_pronoun_reference("Who founded Acme Corporation?") is False
        assert _has_pronoun_reference("What is the internal codename?") is False


# ─── _extract_query_entities ─────────────────────────────────────────────────

class TestExtractQueryEntities:

    # 6. Entity detection — product names
    def test_camelcase_entity(self):
        entities = _extract_query_entities("What is the internal codename for BookWrench?")
        assert "BookWrench" in entities

    def test_quoted_entity(self):
        entities = _extract_query_entities('What does "Wrench-Core" mean?')
        assert "Wrench-Core" in entities

    def test_acronym_entity(self):
        entities = _extract_query_entities("How does JWT authentication work?")
        assert "JWT" in entities

    def test_no_entities_in_common_words(self):
        entities = _extract_query_entities("what is the meaning of this")
        # "this" and "meaning" should not be extracted as entities
        assert len(entities) == 0

    # Multiple entities in one question
    def test_multiple_entities(self):
        entities = _extract_query_entities("How does BookWrench use PostgreSQL and JWT?")
        assert "BookWrench" in entities
        assert "JWT" in entities


# ─── _contextualize_query ────────────────────────────────────────────────────

class TestContextualizeQuery:

    def _hist(self, *pairs) -> list[dict]:
        """Build a minimal conversation history from (role, content) pairs."""
        return [{"role": r, "content": c} for r, c in pairs]

    # 6. Follow-up: pronoun resolved using prior user question
    def test_pronoun_resolved(self):
        history = self._hist(("user", "What is BookWrench?"), ("assistant", "BookWrench is a platform."))
        result = _contextualize_query("Who founded it?", history)
        assert "BookWrench" in result
        assert "Who founded it?" in result

    # Self-contained question — not modified
    def test_no_pronoun_unchanged(self):
        history = self._hist(("user", "What is BookWrench?"))
        result = _contextualize_query("What is the revenue model?", history)
        assert result == "What is the revenue model?"

    # Empty history — question unchanged
    def test_empty_history_unchanged(self):
        result = _contextualize_query("Who founded it?", [])
        assert result == "Who founded it?"

    # Entities from previous assistant reply are also included
    def test_entities_from_assistant_reply(self):
        history = self._hist(
            ("user", "What is the main product?"),
            ("assistant", "The main product is BookWrench, developed by Acme.")
        )
        result = _contextualize_query("When was it released?", history)
        assert "BookWrench" in result or "Acme" in result

    # 9. Ambiguous questions — context injected
    def test_ambiguous_short_followup(self):
        history = self._hist(("user", "Tell me about PostgreSQL."))
        result = _contextualize_query("How does it handle concurrency?", history)
        assert "PostgreSQL" in result

    def test_lowercase_policy_topic_followup(self):
        history = self._hist(("user", "Tell me about remote work."))
        result = _contextualize_query("Would this be allowed for 5 days?", history)
        assert "remote work" in result.lower()


class TestAmbiguityClarification:

    def test_ambiguous_action_without_history_clarifies(self):
        needs_clarification, message = _needs_ambiguity_clarification(
            "Would this action be allowed?",
            [],
        )
        assert needs_clarification is True
        assert "which action" in message.lower()

    def test_ambiguous_rule_without_history_clarifies(self):
        needs_clarification, message = _needs_ambiguity_clarification(
            "Are there any exceptions mentioned to this rule?",
            [],
        )
        assert needs_clarification is True
        assert "which rule" in message.lower()

    def test_ambiguous_followup_with_history_allowed(self):
        history = [{"role": "user", "content": "Tell me about remote work."}]
        needs_clarification, _message = _needs_ambiguity_clarification(
            "Would this action be allowed?",
            history,
        )
        assert needs_clarification is False

    def test_history_context_terms_extract_lowercase_topic(self):
        history = [{"role": "user", "content": "Tell me about remote work."}]
        assert "remote work" in _extract_history_context_terms(history)


class TestQuestionClassification:

    def test_compliance_question_intent(self):
        assert _intent_classify("Would an employee with an 8-character password be compliant?") == "compliance"
        assert _intent_classify("Employee uses a 10-character password. What violations exist?") == "compliance"

    def test_date_and_numeric_calculation_intent(self):
        assert _intent_classify("How many days passed between the two events?") == "arithmetic"
        assert _intent_classify("What is the reimbursement increase?") == "arithmetic"
