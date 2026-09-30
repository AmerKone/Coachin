"""Tests for failed-login rate limiting."""

from fastapi.testclient import TestClient

from app.services.rate_limit import FailureLimiter, login_failures_by_ip
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

LOGIN = "/api/v1/auth/login"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_blocks_after_max_failures_and_expires() -> None:
    clock = FakeClock()
    limiter = FailureLimiter(max_failures=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert limiter.retry_after("k") == 0
        limiter.record_failure("k")
        clock.now += 10
    assert limiter.retry_after("k") == 30          # first failure was 30 s ago; window is 60 s
    assert limiter.retry_after("other") == 0       # keys are independent
    clock.now += 30
    assert limiter.retry_after("k") == 0           # the oldest failure left the window


def test_limiter_reset() -> None:
    limiter = FailureLimiter(max_failures=1, window_seconds=60, clock=FakeClock())
    limiter.record_failure("k")
    assert limiter.retry_after("k") > 0
    limiter.reset("k")
    assert limiter.retry_after("k") == 0


def login(client: TestClient, password: str, email: str = TEST_EMAIL):
    return client.post(LOGIN, data={"username": email, "password": password})


def test_five_failures_lock_the_account_even_for_the_right_password(client: TestClient, registered_user) -> None:
    for _ in range(5):
        assert login(client, "wrong-password").status_code == 401
    locked = login(client, TEST_PASSWORD)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 800            # ~15 minutes
    assert "Too many failed sign-in attempts" in locked.json()["detail"]


def test_success_resets_the_account_counter(client: TestClient, registered_user) -> None:
    for _ in range(4):
        login(client, "wrong-password")
    assert login(client, TEST_PASSWORD).status_code == 200
    for _ in range(4):
        assert login(client, "wrong-password").status_code == 401   # counter restarted from zero
    assert login(client, TEST_PASSWORD).status_code == 200


def test_one_address_trying_many_accounts_is_limited(client: TestClient, registered_user) -> None:
    for i in range(login_failures_by_ip.max_failures):
        assert login(client, "guess", email=f"victim{i}@example.com").status_code == 401
    assert login(client, TEST_PASSWORD).status_code == 429        # the whole address is paused
