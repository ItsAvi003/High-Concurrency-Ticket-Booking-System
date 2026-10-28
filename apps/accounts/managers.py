from django.contrib.auth.base_user import BaseUserManager


def normalize_email_address(email: str) -> str:
    """
    Lowercase the whole address so "Avi@Example.com" and "avi@example.com" are one account.

    Django's built-in normalize_email only lowercases the domain, because RFC 5321 says
    the local part may be case-sensitive. No major provider treats it that way, and
    allowing two accounts that differ only by case is a classic support/security problem.
    """
    return email.strip().lower()


class UserManager(BaseUserManager):
    """Manager for a User model that logs in with email and has no username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        user = self.model(email=normalize_email_address(email), **extra_fields)
        user.set_password(password)  # hashes; never store the raw password
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        # Called by the auth backend at login: make "AVI@x.com" find "avi@x.com".
        return self.get(**{self.model.USERNAME_FIELD: normalize_email_address(email)})
