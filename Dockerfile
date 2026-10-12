FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PALACE_PATH=/data/palace \
    EXPORTS_PATH=/data/exports \
    CONFIG_PATH=/config \
    MEMORY_PORT=8080 \
    MEMPALACE_EXPORTS_DIR=/data/exports \
    MEMPALACE_EMBEDDING_MODEL=all-MiniLM-L6-v2 \
    WING_USER_RETENTION_DAYS=7 \
    MEMPALACE_HOOKS_AUTO_SAVE=true \
    MEMPALACE_EAGER_WARMUP=1 \
    MEMPALACE_TOPIC_TUNNEL_MIN_COUNT=2 \
    MEMPALACE_ENTITY_LANGUAGES=en \
    MEMPALACE_MAX_BACKUPS=10
COPY pyproject.toml README.md ./
COPY src/ src/
COPY mems_cli/ mems_cli/
RUN pip install --no-cache-dir .
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()(['warmup'])"
COPY config/ /config/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS --max-time 4 http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
