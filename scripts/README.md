# scripts

Standalone utilities, run from the repository root with the backend virtualenv active.
Each script adds `backend/` to `sys.path` so it can import `app`.

| Script | Purpose |
|--------|---------|
| `init_db.py` | Create all tables from the ORM models (`Base.metadata.create_all`). Dev only — use Alembic for migrations. |
| `seed_exercises.py [file]` | Load/update the exercise library (default `backend/data/exercises.json`). Safe to re-run. |
| `ingest_knowledge.py [--reset]` | Chunk and embed `knowledge_base/` into Pinecone. |
