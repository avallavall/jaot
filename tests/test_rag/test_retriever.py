"""Tests for RAG retriever: query augmentation, refinement detection, caching.

These are unit tests that don't require Qdrant or Voyage.
Integration tests with in-memory Qdrant are in test_integration.py.
"""

import pytest

from app.services.rag.retriever import (
    RAGRetriever,
    _is_refinement_message,
    build_search_query,
)


class TestBuildSearchQuery:
    """Search query builder enriches refinement messages with context."""

    def test_initial_message_passes_through(self):
        query = build_search_query("I need to optimize delivery routes")
        assert query == "I need to optimize delivery routes"

    def test_initial_message_without_formulation(self):
        query = build_search_query("minimize shipping costs", None)
        assert query == "minimize shipping costs"

    def test_refinement_with_formulation_enriches(self):
        formulation = {
            "problem_name": "Delivery Routing",
            "variables": [
                {"name": "x_ab", "type": "binary"},
                {"name": "load_k", "type": "continuous"},
            ],
        }
        query = build_search_query("add a budget constraint", formulation)
        assert "Delivery Routing" in query
        assert "binary" in query
        assert "continuous" in query
        assert "add a budget constraint" in query

    def test_non_refinement_with_formulation_passes_through(self):
        """Non-refinement messages pass through even if formulation exists."""
        formulation = {"problem_name": "Test", "variables": []}
        query = build_search_query("I want to solve a scheduling problem", formulation)
        assert query == "I want to solve a scheduling problem"

    def test_refinement_with_empty_variables(self):
        formulation = {"problem_name": "Test", "variables": []}
        query = build_search_query("add a constraint", formulation)
        # Pin one expected format: "Variables: ." (with trailing period from the
        # join + sentence punctuation), full query carries name + modification
        assert query == "Optimization problem: Test. Variables: . Modification: add a constraint"

    def test_refinement_deduplicates_variable_types(self):
        formulation = {
            "problem_name": "Test",
            "variables": [
                {"name": "x", "type": "binary"},
                {"name": "y", "type": "binary"},
                {"name": "z", "type": "continuous"},
            ],
        }
        query = build_search_query("remove variable z", formulation)
        # binary should appear once, not twice
        assert query.count("binary") == 1


class TestIsRefinementMessage:
    """Heuristic correctly identifies modification vs. new problem requests."""

    # --- True positives: should be detected as refinements ---

    @pytest.mark.parametrize(
        "message",
        [
            "add a budget constraint",
            "Add constraint for maximum workers",
            "remove variable x",
            "Remove the capacity constraint",
            "change the objective to maximize profit",
            "Change objective function",
            "modify the bounds on production",
            "update the demand constraint",
            "replace the cost function",
            "increase the upper bound to 200",
            "decrease capacity to 50",
            "set the minimum to 10",
            "make it a maximization problem",
            "delete the third constraint",
            "drop variable z",
        ],
    )
    def test_refinement_detected(self, message: str):
        assert _is_refinement_message(message) is True, f"Should be refinement: {message}"

    @pytest.mark.parametrize(
        "message",
        [
            "what if we add another warehouse",
            "instead of minimizing cost, maximize profit",
            "can you add a time window constraint",
            "can you change the objective",
        ],
    )
    def test_embedded_refinement_detected(self, message: str):
        assert _is_refinement_message(message) is True, f"Should be refinement: {message}"

    # --- True negatives: should NOT be detected as refinements ---

    @pytest.mark.parametrize(
        "message",
        [
            "I need to optimize my delivery routes",
            "minimize the total shipping cost for 10 stores",
            "how do I model a knapsack problem",
            "solve a scheduling problem with 5 workers",
            "I have 3 trucks and 20 customers",
            "optimize warehouse layout",
            "find the shortest path between cities",
        ],
    )
    def test_new_problem_not_refinement(self, message: str):
        assert _is_refinement_message(message) is False, f"Should NOT be refinement: {message}"


class TestFakeEmbedClient:
    """FakeEmbedClient produces deterministic vectors."""

    def test_same_text_same_vector(self, fake_embed):
        r1 = fake_embed.embed(texts=["knapsack"], input_type="query")
        r2 = fake_embed.embed(texts=["knapsack"], input_type="query")
        assert r1.embeddings[0] == r2.embeddings[0]

    def test_different_text_different_vector(self, fake_embed):
        r1 = fake_embed.embed(texts=["knapsack"], input_type="query")
        r2 = fake_embed.embed(texts=["scheduling"], input_type="query")
        assert r1.embeddings[0] != r2.embeddings[0]

    def test_vector_dimension(self, fake_embed):
        result = fake_embed.embed(texts=["test"], input_type="query")
        assert len(result.embeddings[0]) == 384

    def test_vector_is_normalized(self, fake_embed):
        import math

        result = fake_embed.embed(texts=["test"], input_type="query")
        vec = result.embeddings[0]
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_batch_embedding(self, fake_embed):
        result = fake_embed.embed(
            texts=["one", "two", "three"],
            input_type="document",
        )
        assert len(result.embeddings) == 3
        assert result.total_tokens > 0

    def test_tracks_calls(self, fake_embed):
        fake_embed.embed(texts=["test"], input_type="query")
        assert fake_embed.call_count == 1
        assert fake_embed.last_input_type == "query"


class TestRetrieverCacheKey:
    """Cache key generation is deterministic and collision-resistant."""

    def test_same_text_same_key(self):
        key1 = RAGRetriever._cache_key("knapsack problem")
        key2 = RAGRetriever._cache_key("knapsack problem")
        assert key1 == key2

    def test_different_text_different_key(self):
        key1 = RAGRetriever._cache_key("knapsack problem")
        key2 = RAGRetriever._cache_key("scheduling problem")
        assert key1 != key2

    def test_key_has_prefix(self):
        key = RAGRetriever._cache_key("test")
        assert key.startswith("rag:emb:")

    def test_key_length_consistent(self):
        key1 = RAGRetriever._cache_key("short")
        key2 = RAGRetriever._cache_key("a much longer query about optimization")
        # Prefix (8) + hash (16) = 24 characters
        assert len(key1) == len(key2) == 24
