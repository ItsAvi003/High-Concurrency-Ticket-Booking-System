"""Shared pytest fixtures, available to every test in the project."""

import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.events.models import Event, Venue
from apps.events.services import create_event_with_seats

DEFAULT_TEST_PASSWORD = "Str0ng-Test-Pass!"


@pytest.fixture
def password():
    """The password every make_user() user has, so tests can log in with it."""
    return DEFAULT_TEST_PASSWORD


@pytest.fixture
def api_client():
    """Unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def make_user(db):
    """Factory: make_user(role=User.Role.ORGANIZER, email=...) -> saved User."""
    sequence = itertools.count(1)

    def _make_user(role=User.Role.USER, **fields):
        fields.setdefault("email", f"{role}{next(sequence)}@example.com")
        fields.setdefault("password", DEFAULT_TEST_PASSWORD)
        return User.objects.create_user(role=role, **fields)

    return _make_user


@pytest.fixture
def customer(make_user):
    return make_user(role=User.Role.USER)


@pytest.fixture
def organizer(make_user):
    return make_user(role=User.Role.ORGANIZER)


@pytest.fixture
def platform_admin(make_user):
    # Not named `admin_user`: that is a built-in pytest-django fixture (a superuser).
    return make_user(role=User.Role.ADMIN)


@pytest.fixture
def client_for():
    """
    Factory: client_for(user) -> APIClient sending a real JWT access token.

    Uses a real token (not force_authenticate) so tests exercise the whole auth stack:
    header parsing, signature check, expiry check, and loading the user from the DB.
    """

    def _client_for(user):
        client = APIClient()
        access = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client

    return _client_for


@pytest.fixture
def make_venue(db):
    """Factory: make_venue(rows=3, seats_per_row=4, ...) -> saved Venue (12 seats by default)."""
    sequence = itertools.count(1)

    def _make_venue(**fields):
        fields.setdefault("name", f"Venue {next(sequence)}")
        fields.setdefault("city", "Pune")
        fields.setdefault("rows", 3)
        fields.setdefault("seats_per_row", 4)
        return Venue.objects.create(**fields)

    return _make_venue


@pytest.fixture
def make_event(make_user, make_venue):
    """
    Factory: make_event(status=..., starts_in=timedelta(...), ...) -> Event with seats.

    Goes through create_event_with_seats, the same code path as the API.
    """
    sequence = itertools.count(1)

    def _make_event(
        *,
        organizer=None,
        venue=None,
        status=Event.Status.PUBLISHED,
        starts_in=timedelta(days=7),
        duration=timedelta(hours=3),
        price=Decimal("499.00"),
        **fields,
    ):
        starts_at = timezone.now() + starts_in
        event = create_event_with_seats(
            organizer=organizer or make_user(role=User.Role.ORGANIZER),
            venue=venue or make_venue(),
            title=fields.pop("title", f"Event {next(sequence)}"),
            starts_at=starts_at,
            ends_at=starts_at + duration,
            price=price,
            **fields,
        )
        if status != Event.Status.DRAFT:
            # Set directly: tests may need states (e.g. a past published event) that the
            # API would refuse to create.
            Event.objects.filter(pk=event.pk).update(status=status)
            event.refresh_from_db()
        return event

    return _make_event
