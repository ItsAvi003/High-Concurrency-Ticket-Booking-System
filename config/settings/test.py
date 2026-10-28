from .base import *  # noqa: F403
from .base import CACHES, build_logging_config

DEBUG = False

# Hashing passwords with PBKDF2 is deliberately slow; tests create many users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Keep test keys apart from dev keys in the shared Redis instance.
CACHES["default"]["KEY_PREFIX"] = "test"

LOGGING = build_logging_config(level="WARNING", json_logs=False)
