import pytest
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.serializers import RegisterSerializer

pytestmark = pytest.mark.django_db

REGISTER_URL = reverse("accounts:register")


STRONG_PASSWORD = "Str0ng-Signup-Pass!"


def _payload(**overrides):
    payload = {
        "email": "new.user@example.com",
        "password": STRONG_PASSWORD,
        "first_name": "Avi",
        "last_name": "Das",
    }
    payload.update(overrides)
    return payload


def test_register_creates_plain_user_and_hides_password(api_client):
    response = api_client.post(REGISTER_URL, _payload())

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert body["role"] == "user"
    assert "password" not in body
    assert User.objects.get(email="new.user@example.com").check_password(STRONG_PASSWORD)


def test_register_cannot_self_assign_privileged_role(api_client):
    # Privilege escalation attempt: extra fields are ignored, not trusted.
    response = api_client.post(
        REGISTER_URL, _payload(role="admin", is_staff=True, is_superuser=True)
    )

    assert response.status_code == 201
    user = User.objects.get(email="new.user@example.com")
    assert user.role == User.Role.USER
    assert not user.is_staff and not user.is_superuser


def test_register_rejects_duplicate_email_case_insensitively(api_client, make_user):
    make_user(email="taken@example.com")

    response = api_client.post(REGISTER_URL, _payload(email="TAKEN@Example.com"))

    assert response.status_code == 400
    assert "email" in response.json()


@pytest.mark.parametrize("weak_password", ["short", "password123", "12345678901"])
def test_register_rejects_weak_passwords(api_client, weak_password):
    response = api_client.post(REGISTER_URL, _payload(password=weak_password))

    assert response.status_code == 400
    assert "password" in response.json()
    assert not User.objects.filter(email="new.user@example.com").exists()


def test_register_rejects_password_similar_to_email(api_client):
    response = api_client.post(
        REGISTER_URL, _payload(email="avishek.das@example.com", password="avishek.das")
    )

    assert response.status_code == 400
    assert "password" in response.json()


def test_register_ignores_garbage_authorization_header(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

    response = api_client.post(REGISTER_URL, _payload())

    assert response.status_code == 201


def test_duplicate_insert_race_returns_validation_error_not_500(make_user):
    # Simulate the race: validation passes, then another request inserts the same email
    # before our INSERT runs. The DB unique index must catch it.
    serializer = RegisterSerializer(data=_payload(email="race@example.com"))
    assert serializer.is_valid(), serializer.errors

    make_user(email="race@example.com")

    with pytest.raises(ValidationError) as exc_info:
        serializer.save()

    assert "email" in exc_info.value.detail
    assert User.objects.filter(email="race@example.com").count() == 1
