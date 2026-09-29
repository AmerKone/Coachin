"""Shared pytest fixtures.

Planned fixtures:
- `db`: a transactional session against a throwaway Postgres database, rolled back per test.
- `client`: a FastAPI `TestClient` with `get_db` overridden to use `db`.
- `user` / `auth_headers`: a persisted user and a valid bearer token.
- `fake_openai`: monkeypatches `app.services.llm_client` so tests never call the real API.
"""
