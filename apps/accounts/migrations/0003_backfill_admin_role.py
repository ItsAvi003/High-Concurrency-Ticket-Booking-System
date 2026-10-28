# Data migration: superusers created before roles existed got the default role "user".
# Promote them so they keep admin powers in the API.

from django.db import migrations


def promote_superusers(apps, schema_editor):
    # Use the historical model from `apps`, never `from apps.accounts.models import User`:
    # the real model may have fields that don't exist yet at this point in history.
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_superuser=True).update(role="admin")


def demote_superusers(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_superuser=True).update(role="user")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_role"),
    ]

    operations = [
        migrations.RunPython(promote_superusers, demote_superusers),
    ]
