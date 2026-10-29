from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base: adds created_at / updated_at to any model that inherits it."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True  # no table of its own; fields are copied into each subclass
