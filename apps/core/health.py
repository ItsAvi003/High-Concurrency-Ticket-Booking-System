"""
Dependency checks used by the readiness endpoint.

Each check raises on failure; the view decides how to report it. Timeouts are short
on purpose: a health probe that hangs is worse than one that says "down".
"""

import redis
from django.conf import settings
from django.db import connection

REDIS_TIMEOUT_SECONDS = 1


def check_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def check_redis() -> None:
    client = redis.Redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


READINESS_CHECKS = {
    "database": check_database,
    "redis": check_redis,
}
