"""Shared pytest fixtures.

Database tests run against `TEST_DATABASE_URL` if set, otherwise the `DATABASE_URL` from
`.env`. Every test runs inside a transaction that is rolled back afterwards, so no rows
are left behind. Tests needing the database are skipped if it is unreachable.
"""

import os
from collections.abc import Iterator

# Must be set before `app` is imported: settings are read once and cached.
if test_db := os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = test_db
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes-long")
os.environ["OPENAI_API_KEY"] = "test-openai-key"      # tests must never call real APIs
os.environ["PINECONE_API_KEY"] = "test-pinecone-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@pytest.fixture(scope="session")
def engine() -> Engine:
    from app.database import engine
    from app.models import Base

    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.skip(f"Database unavailable: {exc.orig}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session bound to an outer transaction that is rolled back after the test.

    `commit()` inside app code only releases a SAVEPOINT, so the outer rollback undoes it.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


TEST_EMAIL = "alex@example.com"
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture
def registered_user(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD, "full_name": "Alex"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth_headers(client: TestClient, registered_user: dict) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
