FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY config/ config/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8787

ENTRYPOINT ["./entrypoint.sh"]
