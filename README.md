# Coachin

An AI fitness coaching agent you talk to. Coachin builds personalized weekly training
programs, tracks workouts with progressive overload, logs nutrition, produces monthly
progress reports, and applies safety guardrails when medical concerns come up.

## Architecture

```
┌──────────────┐   HTTP/JSON + audio   ┌──────────────────────────────┐
│  Streamlit   │ ────────────────────▶ │           FastAPI            │
│  frontend/   │ ◀──────────────────── │           backend/           │
└──────────────┘                       │                              │
                                       │  api/ ─▶ services/ ─▶ agent/ │
                                       │               │         │    │
                                       │          models/      rag/   │
                                       └───────┬───────────┬─────┬────┘
                                               │           │     │
                                          PostgreSQL    OpenAI  Pinecone
                                                     (LLM, Whisper, TTS)
```

## Repository layout

| Path | Purpose |
|------|---------|
| [backend/](backend/) | FastAPI app: REST API, ORM models, Pydantic schemas, services, coaching agent, RAG |
| [frontend/](frontend/) | Streamlit UI: voice chat, program view, workout/nutrition logging, progress charts |
| [knowledge_base/](knowledge_base/) | Source documents ingested into Pinecone for retrieval |
| [scripts/](scripts/) | One-off utilities: DB initialisation, knowledge-base ingestion, seeding |

## Getting started

Requires Python 3.11+ and a running PostgreSQL instance.

```bash
cp .env.example .env               # then fill in API keys

python -m venv .venv
.venv\Scripts\activate             # Windows  (source .venv/bin/activate on macOS/Linux)

pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt

python scripts/init_db.py          # create tables
uvicorn app.main:app --reload --app-dir backend
streamlit run frontend/app.py
```

API docs are served at http://localhost:8000/docs once the backend is running.

## Status

Scaffolding only: models and schemas are defined; routes, services, the agent, and RAG
are stubbed with signatures and docstrings and raise `NotImplementedError`.
