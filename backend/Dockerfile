# Praxis Vaulted Execution Proxy — production image (Cloud Run, asia-south1)
# Build context = REPO ROOT (the image needs backend/ AND evals/):
#   docker build -f backend/Dockerfile -t praxis-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# Dependencies first for layer caching
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Application + red-team suite, PDF fixtures and the latest verified benchmark JSON
COPY backend/ backend/
COPY evals/ evals/

# Non-root runtime user (SQLite fallback DB + embedding cache live under /app/backend)
RUN useradd --create-home --uid 10001 praxis && chown -R praxis:praxis /app
USER praxis
WORKDIR /app/backend

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
