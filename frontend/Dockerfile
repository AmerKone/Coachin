# Coachin frontend: Streamlit. Build from the repository root:
#   docker build -f frontend/Dockerfile -t coachin-frontend .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app/frontend

COPY frontend/requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY frontend/ .

RUN useradd --create-home --uid 10001 coachin && chown -R coachin /app
USER coachin

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
