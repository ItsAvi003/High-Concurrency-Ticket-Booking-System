import pytest
from django.urls import reverse

from apps.core import health


def test_liveness_returns_ok_without_touching_dependencies(client):
    # No django_db mark: if this view queried the database, pytest-django would fail the test.
    response = client.get(reverse("core:health-live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_ok_when_postgres_and_redis_are_up(client):
    response = client.get(reverse("core:health-ready"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.django_db
def test_readiness_503_when_redis_is_unreachable(client, settings):
    # A real connection attempt to a port nothing listens on, not a mock.
    settings.REDIS_URL = "redis://127.0.0.1:1/0"

    response = client.get(reverse("core:health-ready"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "redis": "unavailable"},
    }


@pytest.mark.django_db
def test_readiness_503_when_database_check_fails(client, monkeypatch):
    def broken_database():
        raise ConnectionError("could not connect to server")

    monkeypatch.setitem(health.READINESS_CHECKS, "database", broken_database)

    response = client.get(reverse("core:health-ready"))

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["database"] == "unavailable"
    # Internal error details must not leak to callers.
    assert "could not connect" not in response.content.decode()


def test_health_endpoints_reject_non_get(client):
    response = client.post(reverse("core:health-live"))

    assert response.status_code == 405
