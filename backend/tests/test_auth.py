"""API tests for registration, login, and token-protected access."""

from fastapi.testclient import TestClient

from tests.conftest import TEST_EMAIL, TEST_PASSWORD

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/users/me"


def test_register_returns_user_without_password(registered_user: dict) -> None:
    assert registered_user["email"] == TEST_EMAIL
    assert registered_user["full_name"] == "Alex"
    assert registered_user["is_active"] is True
    assert "password" not in registered_user
    assert "hashed_password" not in registered_user


def test_register_normalizes_email_and_rejects_duplicates(client: TestClient, registered_user: dict) -> None:
    response = client.post(REGISTER, json={"email": TEST_EMAIL.upper(), "password": "another-password"})
    assert response.status_code == 409


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(REGISTER, json={"email": "short@example.com", "password": "short"})
    assert response.status_code == 422


def test_register_rejects_password_over_72_bytes(client: TestClient) -> None:
    response = client.post(REGISTER, json={"email": "long@example.com", "password": "é" * 40})
    assert response.status_code == 422


def test_login_is_case_insensitive_on_email(client: TestClient, registered_user: dict) -> None:
    response = client.post(LOGIN, data={"username": TEST_EMAIL.upper(), "password": TEST_PASSWORD})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_login_wrong_password_and_unknown_email_look_the_same(client: TestClient, registered_user: dict) -> None:
    wrong_password = client.post(LOGIN, data={"username": TEST_EMAIL, "password": "nope-nope-nope"})
    unknown_email = client.post(LOGIN, data={"username": "nobody@example.com", "password": TEST_PASSWORD})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_me_requires_valid_token(client: TestClient) -> None:
    assert client.get(ME).status_code == 401
    assert client.get(ME, headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_me_returns_current_user(client: TestClient, auth_headers: dict) -> None:
    response = client.get(ME, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == TEST_EMAIL


def test_change_password(client: TestClient, auth_headers: dict) -> None:
    response = client.patch(ME, json={"password": "brand-new-password"}, headers=auth_headers)
    assert response.status_code == 200

    assert client.post(LOGIN, data={"username": TEST_EMAIL, "password": TEST_PASSWORD}).status_code == 401
    assert client.post(LOGIN, data={"username": TEST_EMAIL, "password": "brand-new-password"}).status_code == 200


def test_delete_account_invalidates_token(client: TestClient, auth_headers: dict) -> None:
    assert client.delete(ME, headers=auth_headers).status_code == 204
    assert client.get(ME, headers=auth_headers).status_code == 401
