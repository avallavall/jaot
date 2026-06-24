"""Fixtures for RAG tests.

Uses FakeEmbedClient (deterministic vectors) and Qdrant in-memory mode.
No external services required — all tests run offline.

Overrides parent conftest DB fixtures so these tests run without PostgreSQL.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import pytest


# Override parent conftest autouse fixtures that require PostgreSQL
@pytest.fixture(autouse=True)
def _override_db_dependency():
    """No-op override — RAG tests don't need database fixtures."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    """No-op override — RAG tests don't need rate limiter."""
    yield


@pytest.fixture(autouse=True)
def _seed_platform_settings():
    """No-op override — RAG tests don't need platform settings seeding."""
    yield


@dataclass
class FakeEmbedResult:
    """Mimics the SentenceTransformerClient embed() response."""

    embeddings: list[list[float]]
    total_tokens: int


class FakeEmbedClient:
    """Deterministic embedding client for testing.

    Produces 384-dim vectors from a hash of the input text.
    Same text always produces the same vector, enabling assertions
    on retrieval results. Different texts produce different vectors
    with low cosine similarity.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self.call_count = 0
        self.last_texts: list[str] = []
        self.last_input_type: str = ""

    def embed(
        self,
        texts: list[str],
        model: str = "",
        input_type: str = "document",
        **kwargs: Any,
    ) -> FakeEmbedResult:
        """Generate deterministic embeddings from text hashes."""
        self.call_count += 1
        self.last_texts = texts
        self.last_input_type = input_type

        embeddings = [self._text_to_vector(t) for t in texts]
        total_tokens = sum(len(t.split()) for t in texts)
        return FakeEmbedResult(embeddings=embeddings, total_tokens=total_tokens)

    def _text_to_vector(self, text: str) -> list[float]:
        """Hash text into a deterministic unit vector."""
        digest = hashlib.sha256(text.encode()).digest()
        # Expand hash to fill dimension (repeat hash bytes if needed)
        expanded = digest * (self._dimension // len(digest) + 1)
        raw = [b / 255.0 - 0.5 for b in expanded[: self._dimension]]
        # Normalize to unit vector (cosine similarity requires this)
        norm = math.sqrt(sum(x * x for x in raw))
        if norm == 0:
            return [0.0] * self._dimension
        return [x / norm for x in raw]


SAMPLE_TEMPLATE_DOC = {
    "id": "tmpl_knapsack_logistics",
    "text": (
        "This is a JAOT optimization template for Logistics problems "
        "involving Item Selection (Knapsack). "
        "Template: Item Selection (Knapsack)\n"
        "Category: Logistics\n"
        "Archetype: 0-1 knapsack (combinatorial, NP-hard)\n"
        "Problem Type: MIP\n"
        "Summary: Select items to maximize value under capacity.\n"
        "Keywords: logistics, selection, packing, capacity\n"
        "Generator: knapsack"
    ),
    "payload": {
        "doc_type": "template",
        "template_id": "knapsack",
        "category": "logistics",
        "generator_type": "knapsack",
        "problem_type_tags": ["MIP"],
        "tags": ["logistics", "selection", "packing", "capacity"],
        "display_name": "Item Selection (Knapsack)",
        "is_featured": True,
        "estimated_variables": 8,
        "estimated_constraints": 1,
        "source_file": "logistics.yaml",
    },
}

SAMPLE_CONSTRAINT_DOC = {
    "id": "cstr_capacity",
    "text": (
        "This is a reusable constraint pattern called Capacity Constraint "
        "for mathematical optimization formulations. "
        "Constraint Pattern: Capacity Constraint\n"
        "Canonical Form: sum(weight_i * x_i) <= capacity\n"
        "Description: Ensures total resource usage does not exceed available capacity."
    ),
    "payload": {
        "doc_type": "constraint_pattern",
        "pattern_name": "Capacity Constraint",
        "pattern_id": "capacity",
        "used_in": ["knapsack", "bin_packing", "routing"],
    },
}

SAMPLE_LINEARIZATION_DOC = {
    "id": "lin_product_of_binaries",
    "text": (
        "This is a linearization technique called Product of Binary Variables "
        "for reformulating nonlinear expressions into linear constraints. "
        "Linearization: z = x * y where x, y binary\n"
        "Reformulation: z <= x, z <= y, z >= x + y - 1"
    ),
    "payload": {
        "doc_type": "linearization",
        "technique_name": "Product of Binary Variables",
        "technique_id": "product_of_binaries",
    },
}

SAMPLE_GENERATOR_DOC = {
    "id": "gen_routing",
    "text": (
        "This is a JAOT code generator for routing optimization problems. "
        "Generator: routing\n"
        "Archetype: vehicle routing CVRP (combinatorial, NP-hard)\n"
        "Description: Solves CVRP with capacity constraints and subtour elimination."
    ),
    "payload": {
        "doc_type": "generator",
        "generator_type": "routing",
        "source_file": "generators/routing.py",
    },
}

SAMPLE_VOCABULARY_DOC = {
    "id": "vocab_logistics",
    "text": (
        "This maps industry-specific terminology from Logistics "
        "to optimization problem types and generators. "
        "Industry: Logistics\n"
        'Optimization terms:\n  - "Knapsack" -> knapsack generator\n'
        '  - "Vehicle Routing" -> routing generator'
    ),
    "payload": {
        "doc_type": "industry_vocabulary",
        "category": "logistics",
        "category_display": "Logistics & Distribution",
        "generator_types": ["knapsack", "routing"],
        "tags": ["logistics", "routing"],
    },
}

ALL_SAMPLE_DOCS = [
    SAMPLE_TEMPLATE_DOC,
    SAMPLE_CONSTRAINT_DOC,
    SAMPLE_LINEARIZATION_DOC,
    SAMPLE_GENERATOR_DOC,
    SAMPLE_VOCABULARY_DOC,
]


@pytest.fixture
def fake_embed() -> FakeEmbedClient:
    """A FakeEmbedClient instance for testing."""
    return FakeEmbedClient()


@pytest.fixture
def sample_docs() -> list[dict[str, Any]]:
    """The 5 sample documents for seeding Qdrant."""
    return list(ALL_SAMPLE_DOCS)
