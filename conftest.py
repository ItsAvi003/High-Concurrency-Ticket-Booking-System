"""Shared pytest fixtures, available to every test in the project."""

import itertools

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User

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
