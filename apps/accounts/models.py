"""
Custom user model.

Created in Phase 0, before the very first migration, because swapping
AUTH_USER_MODEL later means rewriting every foreign key to the user table by hand.

`role` drives API authorization (apps/accounts/permissions.py). It is separate from
Django's is_staff / is_superuser, which only control access to the /admin/ site.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.accounts.managers import UserManager, normalize_email_address


class User(AbstractUser):
    class Role(models.TextChoices):
        USER = "user", "User"  # books tickets
        ORGANIZER = "organizer", "Organizer"  # creates and manages events
        ADMIN = "admin", "Admin"  # manages the platform, including other users' roles

    # Remove the inherited username column entirely; email is the login identifier.
    username = None
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)

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
