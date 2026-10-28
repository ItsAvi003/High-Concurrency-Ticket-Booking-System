from .base import *  # noqa: F403
from .base import LOG_LEVEL, build_logging_config, env

DEBUG = True
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])

# Human-readable logs locally unless LOG_JSON=true is set explicitly.
LOGGING = build_logging_config(level=LOG_LEVEL, json_logs=env.bool("LOG_JSON", default=False))
