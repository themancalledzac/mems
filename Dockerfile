FROM python:3.12-slim

# System deps: git for sync-engine diff, curl for healthcheck probe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Canonical runtime env — see CONTEXT.md §5.
# Kept in sync with what src/mcp_http_server.py, src/wing_user_snapshot.py,
# and src/restore_wing_user.py actually read at runtime.
ENV PALACE_PATH=/data/palace \
    EXPORTS_PATH=/data/exports \
    CONFIG_PATH=/config \
    MEMORY_PORT=8080 \
    MEMPALACE_EXPORTS_DIR=/data/exports \
    EMBEDDING_MODEL=all-MiniLM-L6-v2 \
    WING_USER_RETENTION_DAYS=7

# Install project + deps. Copy pyproject + sources needed for the build backend.
COPY pyproject.toml ./
COPY src/ src/
COPY mems_cli/ mems_cli/
RUN pip install --no-cache-dir .

# Pre-download the embedding model so cold start waits once (build-time) not
# every container boot. Uses the same model string pinned in ENV above.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Runtime-only assets (config + entrypoint) copied last so source edits don't
# bust the pip-install or model-warmup layers.
COPY config/ /config/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
