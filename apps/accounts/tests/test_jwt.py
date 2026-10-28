import pytest
from django.urls import reverse
from freezegun import freeze_time

pytestmark = pytest.mark.django_db

LOGIN_URL = reverse("accounts:token-obtain")
REFRESH_URL = reverse("accounts:token-refresh")
LOGOUT_URL = reverse("accounts:logout")
ME_URL = reverse("accounts:me")


@pytest.fixture
def login(api_client, password):
    """login(email, password=<the fixture password>) -> response from the token endpoint."""

    def _login(email, password=password):
        return api_client.post(LOGIN_URL, {"email": email, "password": password})

    return _login


def test_login_returns_access_and_refresh_tokens(api_client, customer, login):
    response = login(customer.email)

    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}


def test_login_is_case_insensitive_on_email(api_client, customer, login):
    response = login(customer.email.upper())

    assert response.status_code == 200


def test_login_with_wrong_password_is_401(api_client, customer, login):
    response = login(customer.email, password="wrong-password")

    assert response.status_code == 401


def test_login_error_does_not_reveal_whether_email_exists(api_client, customer, login):
    wrong_password = login(customer.email, password="wrong-password")
    unknown_email = login("nobody@example.com")

    # Same status and message, so the endpoint can't be used to discover registered emails.
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_inactive_user_cannot_log_in(api_client, customer, login):
    customer.is_active = False
    customer.save()

    assert login(customer.email).status_code == 401


def test_access_token_authenticates_requests(api_client, customer, login):
    access = login(customer.email).json()["access"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    response = api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["email"] == customer.email
    assert response.json()["role"] == "user"


def test_missing_token_is_401_with_www_authenticate_header(api_client):
    response = api_client.get(ME_URL)

    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_tampered_token_is_rejected(api_client, customer, login):
    access = login(customer.email).json()["access"]
    # Flip one character in the signature (the part after the last dot).
    tampered = access[:-1] + ("A" if access[-1] != "A" else "B")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tampered}")

    assert api_client.get(ME_URL).status_code == 401


def test_expired_access_token_is_rejected(api_client, customer, login):
    with freeze_time("2026-01-01 12:00:00"):
        access = login(customer.email).json()["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    with freeze_time("2026-01-01 12:16:00"):  # lifetime is 15 minutes
        response = api_client.get(ME_URL)

    assert response.status_code == 401


def test_refresh_returns_new_tokens_and_old_refresh_is_blacklisted(api_client, customer, login):
    old_refresh = login(customer.email).json()["refresh"]

    first = api_client.post(REFRESH_URL, {"refresh": old_refresh})
    assert first.status_code == 200
    assert set(first.json()) == {"access", "refresh"}
    assert first.json()["refresh"] != old_refresh

    # Reusing the rotated-out refresh token must fail.
    replay = api_client.post(REFRESH_URL, {"refresh": old_refresh})
    assert replay.status_code == 401


def test_logout_blacklists_refresh_token(api_client, customer, login):
    refresh = login(customer.email).json()["refresh"]

    logout = api_client.post(LOGOUT_URL, {"refresh": refresh})
    assert logout.status_code == 200

    assert api_client.post(REFRESH_URL, {"refresh": refresh}).status_code == 401


def test_access_token_cannot_be_used_as_refresh_token(api_client, customer, login):
    access = login(customer.email).json()["access"]

    assert api_client.post(REFRESH_URL, {"refresh": access}).status_code == 401
