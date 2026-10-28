"""Endpoint tests: every role against every protected endpoint."""

import pytest
from django.urls import reverse

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

USER_LIST_URL = reverse("accounts:user-list")
ME_URL = reverse("accounts:me")


def role_url(user):
    return reverse("accounts:user-role", kwargs={"pk": user.pk})


@pytest.fixture
def users_by_role(customer, organizer, platform_admin):
    return {"user": customer, "organizer": organizer, "admin": platform_admin}


# --- /auth/me/ ------------------------------------------------------------------


@pytest.mark.parametrize("role", ["user", "organizer", "admin"])
def test_me_works_for_every_role(client_for, users_by_role, role):
    response = client_for(users_by_role[role]).get(ME_URL)

    assert response.status_code == 200
    assert response.json()["role"] == role


# --- GET /users/ ----------------------------------------------------------------


def test_user_list_requires_authentication(api_client):
    assert api_client.get(USER_LIST_URL).status_code == 401


@pytest.mark.parametrize("role", ["user", "organizer"])
def test_user_list_forbidden_for_non_admins(client_for, users_by_role, role):
    response = client_for(users_by_role[role]).get(USER_LIST_URL)

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required."}


def test_user_list_for_admin_is_paginated_and_hides_passwords(client_for, users_by_role):
    response = client_for(users_by_role["admin"]).get(USER_LIST_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert {"count", "next", "previous", "results"} <= set(body)
    assert all("password" not in user for user in body["results"])


# --- PATCH /users/<id>/role/ ------------------------------------------------------


@pytest.mark.parametrize("role", ["user", "organizer"])
def test_non_admins_cannot_change_roles(client_for, users_by_role, customer, role):
    response = client_for(users_by_role[role]).patch(role_url(customer), {"role": "admin"})

    assert response.status_code == 403
    customer.refresh_from_db()
    assert customer.role == User.Role.USER


def test_admin_can_promote_user_to_organizer(client_for, platform_admin, customer):
    response = client_for(platform_admin).patch(role_url(customer), {"role": "organizer"})

    assert response.status_code == 200
    assert response.json() == {"id": customer.pk, "email": customer.email, "role": "organizer"}
    customer.refresh_from_db()
    assert customer.role == User.Role.ORGANIZER


def test_admin_cannot_set_unknown_role(client_for, platform_admin, customer):
    response = client_for(platform_admin).patch(role_url(customer), {"role": "superhero"})

    assert response.status_code == 400
    assert "role" in response.json()


def test_admin_cannot_change_own_role(client_for, platform_admin):
    response = client_for(platform_admin).patch(role_url(platform_admin), {"role": "user"})

    assert response.status_code == 400
    platform_admin.refresh_from_db()
    assert platform_admin.role == User.Role.ADMIN


def test_role_update_only_accepts_patch(client_for, platform_admin, customer):
    response = client_for(platform_admin).put(role_url(customer), {"role": "organizer"})

    assert response.status_code == 405


def test_role_update_for_missing_user_is_404(client_for, platform_admin):
    url = reverse("accounts:user-role", kwargs={"pk": 999_999})

    assert client_for(platform_admin).patch(url, {"role": "organizer"}).status_code == 404


def test_demotion_takes_effect_immediately_for_existing_tokens(client_for, make_user):
    # The role is read from the DB on every request, not from the token, so a token
    # issued while the user was an admin stops granting admin access right away.
    first_admin = make_user(role=User.Role.ADMIN)
    second_admin = make_user(role=User.Role.ADMIN)
    first_admin_client = client_for(first_admin)
    assert first_admin_client.get(USER_LIST_URL).status_code == 200

    demote = client_for(second_admin).patch(role_url(first_admin), {"role": "user"})
    assert demote.status_code == 200

    assert first_admin_client.get(USER_LIST_URL).status_code == 403


def test_createsuperuser_gets_admin_role():
    superuser = User.objects.create_superuser(email="root@example.com", password="x")

    assert superuser.role == User.Role.ADMIN
