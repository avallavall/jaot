# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4 AS builder

# Pin uv for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.6@sha256:4a6c9444b126bd325fba904bff796bf91fb777bf6148d60109c4cb1de2ffc497 /uv /bin/uv

WORKDIR /build

ENV UV_COMPILE_BYTECODE=1

# Install torch CPU-only first so sentence-transformers reuses it instead of pulling default CUDA build
# (~4 GB of unused NVIDIA libs + ~640 MB of triton on a CPU-only host — image-size forensic 2026-05-20).
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --prefix=/install \
        torch --index-url https://download.pytorch.org/whl/cpu \
    && uv pip install --system --compile-bytecode -r requirements.txt --prefix=/install \
    # Remove unused onnxruntime + packaged test suites that ship inside scientific deps.
    && rm -rf /install/lib/python*/site-packages/onnxruntime* \
    && find /install -depth -type d -name 'tests' -exec rm -rf {} + 2>/dev/null \
    && find /install -type f -name '*.pyx' -delete 2>/dev/null \
    && true

FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4 AS runtime

WORKDIR /app

COPY --from=builder /install /usr/local

# Non-root user created before COPY so --chown sets ownership at copy time.
RUN groupadd --gid 1001 jaot \
    && useradd --uid 1001 --gid jaot --shell /bin/false --create-home jaot

COPY --chown=jaot:jaot app/ ./app/
COPY --chown=jaot:jaot run.py .
COPY --chown=jaot:jaot scripts/ ./scripts/
# Operator helper scripts (e.g. replay-daily-task.sh). The deploy runbook
# invokes these as `docker exec jaot_prod_api bash /opt/jaot/deploy/scripts/...`,
# so ship them at that exact path to keep container + runbook consistent (IN-03).
COPY --chown=jaot:jaot deploy/scripts/ /opt/jaot/deploy/scripts/
COPY --chown=jaot:jaot infra/alembic/ ./infra/alembic/
COPY --chown=jaot:jaot infra/alembic.ini ./infra/alembic.ini

# Pre-download sentence-transformers model — read-only fs at runtime blocks the download.
ENV SENTENCE_TRANSFORMERS_HOME=/app/.model_cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')" \
    && chown -R jaot:jaot /app/.model_cache
# Model is baked above; force offline at runtime so RAG loads from the local cache
# instead of contacting the HF Hub on every boot (no network dependency, no log noise).
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN python -m compileall -q ./app/

USER jaot

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8001

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/v2/health/status')"]

CMD ["python", "run.py"]
