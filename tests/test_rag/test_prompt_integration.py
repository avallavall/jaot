"""Tests for RAG prompt integration.

Covers format_rag_document(), format_rag_context(), and the modified
build_system_prompt() with RAG context injection.
"""

from app.services.llm.prompt_templates import (
    FORMULATION_SYSTEM_PROMPT,
    NO_RAG_CONTEXT,
    build_system_prompt,
    format_rag_context,
    format_rag_document,
)

# format_rag_document


class TestFormatRagDocument:
    """Each document type produces a correctly labeled header."""

    def test_template_header(self):
        payload = {
            "doc_type": "template",
            "display_name": "Knapsack",
            "category": "logistics",
            "text": "Template body text",
        }
        result = format_rag_document(payload, 0.92)
        assert "Template: Knapsack" in result
        assert "category: logistics" in result
        assert "relevance: 0.92" in result
        assert "Template body text" in result

    def test_generator_header(self):
        payload = {
            "doc_type": "generator",
            "generator_type": "routing",
            "text": "Generator body",
        }
        result = format_rag_document(payload, 0.85)
        assert "Generator Pattern: routing" in result
        assert "relevance: 0.85" in result

    def test_constraint_pattern_header(self):
        payload = {
            "doc_type": "constraint_pattern",
            "pattern_name": "Capacity Constraint",
            "text": "Constraint body",
        }
        result = format_rag_document(payload, 0.71)
        assert "Constraint Pattern: Capacity Constraint" in result
        assert "relevance: 0.71" in result

    def test_linearization_header(self):
        payload = {
            "doc_type": "linearization",
            "technique_name": "Big-M Calibration",
            "text": "Linearization body",
        }
        result = format_rag_document(payload, 0.65)
        assert "Linearization: Big-M Calibration" in result
        assert "relevance: 0.65" in result

    def test_unknown_type_fallback(self):
        payload = {
            "doc_type": "something_new",
            "text": "Unknown body",
        }
        result = format_rag_document(payload, 0.50)
        assert "Reference" in result
        assert "relevance: 0.50" in result

    def test_missing_payload_fields_use_defaults(self):
        payload = {"doc_type": "template", "text": "body"}
        result = format_rag_document(payload, 0.80)
        assert "Unknown" in result  # default display_name
        assert "general" in result  # default category


# format_rag_context


class TestFormatRagContext:
    """Context block formatting for system prompt injection."""

    def test_empty_results_return_no_rag_context(self):
        result = format_rag_context([])
        assert result == NO_RAG_CONTEXT
        assert "No specific optimization templates" in result

    def test_results_wrapped_in_optimization_knowledge_tags(self):
        results = [
            {
                "text": "body",
                "score": 0.90,
                "payload": {
                    "doc_type": "template",
                    "display_name": "Test",
                    "category": "test",
                    "text": "body",
                },
            }
        ]
        result = format_rag_context(results)
        assert "<optimization_knowledge>" in result
        assert "</optimization_knowledge>" in result

    def test_multiple_results_separated_by_blank_lines(self):
        results = [
            {
                "text": "body1",
                "score": 0.90,
                "payload": {
                    "doc_type": "template",
                    "display_name": "A",
                    "category": "x",
                    "text": "body1",
                },
            },
            {
                "text": "body2",
                "score": 0.70,
                "payload": {"doc_type": "constraint_pattern", "pattern_name": "B", "text": "body2"},
            },
        ]
        result = format_rag_context(results)
        assert "--- Template: A" in result
        assert "--- Constraint Pattern: B" in result

    def test_includes_prioritization_signal(self):
        results = [
            {
                "text": "body",
                "score": 0.90,
                "payload": {
                    "doc_type": "template",
                    "display_name": "T",
                    "category": "c",
                    "text": "body",
                },
            }
        ]
        result = format_rag_context(results)
        assert "ordered by relevance" in result
        assert "first document is the best match" in result

    def test_includes_anti_hallucination_instructions(self):
        results = [
            {
                "text": "body",
                "score": 0.90,
                "payload": {
                    "doc_type": "template",
                    "display_name": "T",
                    "category": "c",
                    "text": "body",
                },
            }
        ]
        result = format_rag_context(results)
        assert "Do NOT mention these templates" in result


# build_system_prompt


class TestBuildSystemPrompt:
    """System prompt builder with RAG context and document context."""

    def test_without_rag_returns_base_prompt(self):
        prompt = build_system_prompt()
        assert prompt == FORMULATION_SYSTEM_PROMPT
        assert "<optimization_knowledge>" not in prompt

    def test_with_rag_context_appended(self):
        rag_ctx = "<optimization_knowledge>test</optimization_knowledge>"
        prompt = build_system_prompt(rag_context=rag_ctx)
        assert FORMULATION_SYSTEM_PROMPT in prompt
        assert "<optimization_knowledge>" in prompt

    def test_with_document_context_appended(self):
        doc_ctx = {
            "filename": "report.pdf",
            "char_count": 5000,
            "extracted_text": "Report content here...",
        }
        prompt = build_system_prompt(document_context=doc_ctx)
        assert "<document_context>" in prompt
        assert "report.pdf" in prompt

    def test_rag_before_document(self):
        """RAG context must come between base instructions and document."""
        rag_ctx = "\n<optimization_knowledge>rag stuff</optimization_knowledge>"
        doc_ctx = {
            "filename": "data.csv",
            "char_count": 100,
            "extracted_text": "csv data",
        }
        prompt = build_system_prompt(document_context=doc_ctx, rag_context=rag_ctx)
        rag_pos = prompt.index("<optimization_knowledge>")
        doc_pos = prompt.index("<document_context>")
        base_end = len(FORMULATION_SYSTEM_PROMPT)
        assert rag_pos >= base_end, "RAG should come after base instructions"
        assert doc_pos > rag_pos, "Document should come after RAG"

    def test_none_rag_context_ignored(self):
        """Explicitly passing None for rag_context is same as omitting it."""
        prompt = build_system_prompt(rag_context=None)
        assert prompt == FORMULATION_SYSTEM_PROMPT
