# Coachin backend

FastAPI service exposing the REST API, coaching agent, voice pipeline, and RAG.

## Layout

```
backend/
├── app/
│   ├── main.py            FastAPI app factory, CORS, router mounting, /health
│   ├── config.py          pydantic-settings `Settings` (reads ../.env)
│   ├── database.py        SQLAlchemy engine, SessionLocal, get_db dependency
│   ├── api/
│   │   ├── deps.py        DbSession / CurrentUser dependencies
│   │   └── routes/        auth, users, exercises, programs, workouts, nutrition,
│   │                      progress, chat, voice, safety  (all under /api/v1)
│   ├── models/            SQLAlchemy 2.0 ORM models + shared enums
│   ├── schemas/           Pydantic v2 request/response models
│   ├── services/          Business logic (program generation, overload, nutrition,
│   │                      reports, safety guardrails, voice, LLM client, auth)
│   ├── agent/             Coaching agent: prompts, tool definitions, tool-calling loop
│   └── rag/               Pinecone vector store, ingestion, retriever
└── tests/
```

Request flow: `routes` validate input with `schemas` → call a `service` → services use
`models` via the session, and call `agent` / `rag` / OpenAI as needed.

## Data model

| Table | Purpose |
|-------|---------|
| `users` | Accounts (email, password hash) |
| `user_profiles` | 1:1 fitness profile: goal, level, schedule, equipment, injuries, macro targets |
| `exercises` | Exercise library with muscles, equipment, contraindications |
| `training_programs` | Multi-week programs (draft/active/completed/archived) |
| `program_workouts` | Planned day within a program (week number + day of week) |
| `planned_exercises` | Prescription: sets × rep range @ load/RPE, rest |
| `workout_sessions` | Workouts actually performed, optionally linked to a planned day |
| `exercise_sets` | Logged sets (reps, weight, RPE) — input to progressive overload |
| `nutrition_logs` | Meals with calories/macros (manual or LLM-estimated) |
| `body_metrics` | Weight, body fat, waist, resting HR over time |
| `progress_reports` | Monthly report: computed metrics JSON + LLM narrative |
| `conversations` / `messages` | Chat history with the coach, incl. tool calls and RAG sources |
| `safety_events` | Audit log of guardrail triggers |

## Running

```bash
pip install -r requirements.txt
python ../scripts/init_db.py
uvicorn app.main:app --reload          # from backend/
pytest
```

For schema changes beyond initial setup, initialise Alembic (`alembic init migrations`) and
point `target_metadata` at `app.models.Base.metadata`.
