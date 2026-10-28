"""
Logging configuration builder.

Every log line goes to stdout (the container runtime collects it) and carries the
current request id. In production the format is one JSON object per line so log
aggregators (Loki, ELK, CloudWatch) can index fields instead of grepping text.
"""


def build_logging_config(level: str, json_logs: bool) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "apps.core.logging.RequestIdFilter"},
        },
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
                "rename_fields": {"asctime": "timestamp", "levelname": "level", "name": "logger"},
            },
            "console": {
                "format": "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json" if json_logs else "console",
                "filters": ["request_id"],
            },
            # Swallows records. Needed because a logger with *no* handlers falls back to
            # Python's "last resort" stderr handler for WARNING and above.
            "null": {"class": "logging.NullHandler"},
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            # Replace Django's default console/mail_admins handlers with ours, so every
            # Django log line is formatted the same way and carries the request id.
            "django": {"handlers": ["stdout"], "level": level, "propagate": False},
            # RequestIdMiddleware already logs each request; drop runserver's duplicate line.
            "django.server": {"handlers": ["null"], "propagate": False},
            # SQL logging is noisy; enable explicitly when debugging queries.
            "django.db.backends": {"level": "WARNING"},
        },
    }
