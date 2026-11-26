import pytest
from django.db import connection


def test_health_check_returns_healthy(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.django_db
def test_tests_run_against_a_separate_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        (name,) = cursor.fetchone()

    assert name.startswith("test_")


@pytest.mark.django_db
def test_readiness_reports_ready_when_everything_is_up(client, monkeypatch):
    monkeypatch.setattr("core.views._redis_is_up", lambda: True)

    response = client.get("/health/ready/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }


@pytest.mark.django_db
def test_readiness_stays_ready_when_only_redis_is_down(client, monkeypatch):
    monkeypatch.setattr("core.views._redis_is_up", lambda: False)

    response = client.get("/health/ready/")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}


@pytest.mark.django_db
def test_readiness_returns_503_when_the_database_is_down(client, monkeypatch):
    monkeypatch.setattr("core.views._database_is_up", lambda: False)
    monkeypatch.setattr("core.views._redis_is_up", lambda: True)

    response = client.get("/health/ready/")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["database"] == "error"


@pytest.mark.django_db
def test_the_database_check_passes_against_a_real_database():
    from core.views import _database_is_up

    assert _database_is_up() is True


def test_the_redis_check_passes_when_the_server_answers(monkeypatch):
    from core.views import _redis_is_up

    class FakeRedis:
        def ping(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr("core.views.redis.Redis.from_url", lambda *a, **k: FakeRedis())

    assert _redis_is_up() is True


def test_the_redis_check_fails_quickly_when_nothing_is_listening(settings):
    from core.views import _redis_is_up

    settings.CELERY_BROKER_URL = "redis://127.0.0.1:1/0"  # nothing listens on port 1

    assert _redis_is_up() is False
