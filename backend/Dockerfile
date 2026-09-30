# Coachin backend: FastAPI + setup scripts. Build from the repository root:
#   docker build -f backend/Dockerfile -t coachin-backend .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Dependencies first so code changes don't reinstall them.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/
COPY knowledge_base/ knowledge_base/

RUN useradd --create-home --uid 10001 coachin && chown -R coachin /app
USER coachin

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

# Create tables and load the exercise library (both idempotent), then serve.
CMD ["sh", "-c", "python scripts/init_db.py && python scripts/seed_exercises.py && exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"]
