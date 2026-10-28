"""Unit tests for the permission classes themselves, independent of any real endpoint."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminRole, IsOrganizer, IsOwnerOrAdminRole

factory = APIRequestFactory()


def _request_as(user):
    request = factory.get("/")
    request.user = user
    return request


def _user(role, pk=1):
    # Unsaved instance: permission classes only read attributes, so no DB is needed.
    return User(pk=pk, email=f"{role}@example.com", role=role)


@pytest.mark.parametrize(
    ("permission_class", "role", "expected"),
    [
        (IsOrganizer, User.Role.USER, False),
        (IsOrganizer, User.Role.ORGANIZER, True),
        (IsOrganizer, User.Role.ADMIN, True),
        (IsAdminRole, User.Role.USER, False),
        (IsAdminRole, User.Role.ORGANIZER, False),
        (IsAdminRole, User.Role.ADMIN, True),
    ],
)
def test_role_permissions(permission_class, role, expected):
    assert permission_class().has_permission(_request_as(_user(role)), view=None) is expected


@pytest.mark.parametrize("permission_class", [IsOrganizer, IsAdminRole, IsOwnerOrAdminRole])
def test_anonymous_user_is_always_denied(permission_class):
    assert permission_class().has_permission(_request_as(AnonymousUser()), view=None) is False


def test_staff_flag_alone_does_not_grant_admin_role():
    staff_but_plain_role = User(pk=1, email="s@example.com", role=User.Role.USER, is_staff=True)

    assert IsAdminRole().has_permission(_request_as(staff_but_plain_role), view=None) is False


@pytest.mark.parametrize(
    ("role", "requester_pk", "owner_pk", "expected"),
    [
        (User.Role.USER, 1, 1, True),  # own object
        (User.Role.USER, 1, 2, False),  # someone else's
        (User.Role.ORGANIZER, 1, 2, False),  # organizers get no special access here
        (User.Role.ADMIN, 1, 2, True),  # admins see everything
    ],
)
def test_owner_or_admin_object_permission(role, requester_pk, owner_pk, expected):
    booking_like = SimpleNamespace(user_id=owner_pk)
    request = _request_as(_user(role, pk=requester_pk))

    assert IsOwnerOrAdminRole().has_object_permission(request, None, booking_like) is expected


def test_owner_field_is_configurable():
    class IsEventOwnerOrAdmin(IsOwnerOrAdminRole):
        owner_field = "organizer"

    event_like = SimpleNamespace(organizer_id=7)
    request = _request_as(_user(User.Role.ORGANIZER, pk=7))

    assert IsEventOwnerOrAdmin().has_object_permission(request, None, event_like) is True
