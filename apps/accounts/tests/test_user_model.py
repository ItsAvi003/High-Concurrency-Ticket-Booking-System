import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_auth_user_model_is_our_custom_user():
    assert User._meta.label == "accounts.User"
    assert User.USERNAME_FIELD == "email"
    assert "username" not in {field.name for field in User._meta.get_fields()}


def test_create_user_lowercases_email_and_hashes_password():
    user = User.objects.create_user(email="  Avi@Example.COM ", password="s3cret-pass")

    assert user.email == "avi@example.com"
    assert user.password != "s3cret-pass"
    assert user.check_password("s3cret-pass")
    assert not user.is_staff
    assert not user.is_superuser


def test_email_is_unique_regardless_of_case():
    User.objects.create_user(email="avi@example.com", password="x")

    with pytest.raises(IntegrityError):
        User.objects.create_user(email="AVI@example.com", password="x")


def test_save_normalizes_email_outside_the_manager_too():
    user = User(email="Mixed@Case.com")
    user.set_password("x")
    user.save()

    assert User.objects.get(pk=user.pk).email == "mixed@case.com"


def test_login_works_with_differently_cased_email():
    User.objects.create_user(email="avi@example.com", password="s3cret-pass")

    assert authenticate(email="AVI@Example.com", password="s3cret-pass") is not None
    assert authenticate(email="avi@example.com", password="wrong") is None


def test_create_user_requires_email():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x")


def test_create_superuser_sets_flags():
    admin = User.objects.create_superuser(email="root@example.com", password="x")

    assert admin.is_staff and admin.is_superuser


def test_create_superuser_rejects_contradicting_flags():
    with pytest.raises(ValueError):
        User.objects.create_superuser(email="root@example.com", password="x", is_staff=False)
