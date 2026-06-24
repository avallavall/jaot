"""Embedding provider for RAG.

Uses sentence-transformers with BAAI/bge-small-en-v1.5 (384 dims, ~130MB).
Exposes .embed(texts, model, input_type) returning an object with
.embeddings and .total_tokens attributes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EmbedResult:
    """Embedding result."""

    embeddings: list[list[float]]
    total_tokens: int


class SentenceTransformerClient:
    """Local embedding client using sentence-transformers.

    Default model: BAAI/bge-small-en-v1.5 (384 dims, ~130MB, best retrieval
    quality in the small model class). Requires query prefix for retrieval.
    """

    # BGE models need this prefix on queries (not documents) for best retrieval
    _BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        self._is_bge = "bge" in model_name.lower()
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info(
            "SentenceTransformer initialized: %s (%d dims)",
            model_name,
            self._dimension,
        )

    @property
    def dimension(self) -> int:
        """Embedding dimension of the loaded model."""
        return self._dimension

    def embed(
        self,
        texts: list[str],
        model: str = "",
        input_type: str = "document",
        **kwargs: object,
    ) -> EmbedResult:
        """Embed texts using the local model.

        The `model` parameter is ignored (local model is fixed at init).
        BGE models prepend a query prefix when ``input_type="query"``.
        """
        encode_texts = (
            [self._BGE_QUERY_PREFIX + t for t in texts]
            if self._is_bge and input_type == "query"
            else texts
        )

        embeddings = self._model.encode(
            encode_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embedding_lists = [emb.tolist() for emb in embeddings]
        total_tokens = sum(len(t.split()) for t in texts)
        return EmbedResult(embeddings=embedding_lists, total_tokens=total_tokens)


def create_embedding_client() -> tuple[SentenceTransformerClient, int]:
    """Create the embedding client.

    Returns (client, dimension) tuple.
    """
    client = SentenceTransformerClient()
    return client, client.dimension
