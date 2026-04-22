# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    GEMINI_COOKIE_PATH=/data/cookies \
    CONFIG_PATH=/config/config.yaml \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY server ./server

RUN pip install ".[server]"

# Non-root user. Mounted /config and /data volumes must be writable by UID 10001.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/cookies /config \
    && chown -R app:app /app /data /config

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2); sys.exit(0 if r.status==200 else 1)"

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
