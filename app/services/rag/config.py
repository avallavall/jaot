"""RAG configuration constants.

Infrastructure values (URLs, API keys) come from ``app.config.Settings``.
Business values (top-k, min score, etc.) come from platform_settings via PSS.
This module holds only hardcoded constants that never change at runtime.
"""

# Qdrant collection name for the JAOT knowledge base
COLLECTION_NAME = "jaot_knowledge"

# Dense vector dimensions (BAAI/bge-small-en-v1.5 default)
DENSE_VECTOR_SIZE = 384

# Embedding batch size for indexing
EMBEDDING_BATCH_SIZE = 50

# Redis cache key prefix and TTL for embedding cache
EMBEDDING_CACHE_PREFIX = "rag:emb:"
EMBEDDING_CACHE_TTL = 3600  # 1 hour

# Circuit breaker defaults
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60  # seconds

# High-confidence threshold for few-shot exemplar injection
# Calibrated with sentence-transformers: top-1 correct scores range 0.33-0.74
HIGH_CONFIDENCE_THRESHOLD = 0.60
