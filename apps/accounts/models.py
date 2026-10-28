"""
Custom user model.

Created in Phase 0, before the very first migration, because swapping
AUTH_USER_MODEL later means rewriting every foreign key to the user table by hand.
Roles are added in Phase 1.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.accounts.managers import UserManager, normalize_email_address


class User(AbstractUser):
    # Remove the inherited username column entirely; email is the login identifier.
    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # prompted by createsuperuser in addition to email + password

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"

    def save(self, *args, **kwargs):
        # Covers every write path (admin, shell, serializers), not just the manager.
        if self.email:
            self.email = normalize_email_address(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email
