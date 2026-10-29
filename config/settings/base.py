"""
Settings shared by every environment.

Anything that differs between environments (secrets, hosts, URLs) is read from
environment variables, never hard-coded. dev.py / prod.py / test.py import this
module and override only what they need.
"""

from datetime import timedelta
from pathlib import Path

import environ

from config.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Lets `python manage.py ...` work outside Docker. Real environment variables take
# precedence over values in the file, so Docker/CI settings are never overridden.
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    # Local apps
    "apps.core",
    "apps.accounts",
    "apps.events",
    "apps.bookings",
]

MIDDLEWARE = [
    # First, so every later middleware, view and log line can see the request id.
    "apps.core.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -----------------------------------------------------------------
DATABASES = {"default": env.db("DATABASE_URL")}
# Reuse connections for 60s instead of opening one per request.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
# Detect connections that died while idle (e.g. Postgres restarted) before using them.
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
# Fail fast instead of hanging if Postgres is unreachable.
DATABASES["default"].setdefault("OPTIONS", {})["connect_timeout"] = 5

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Redis / cache ------------------------------------------------------------
REDIS_URL = env("REDIS_URL")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "TIMEOUT": 300,
    }
}

# --- Auth ---------------------------------------------------------------------
# Must be set before the first migration; see apps/accounts/models.py.
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Django REST Framework ------------------------------------------------------
REST_FRAMEWORK = {
    # Stateless bearer tokens only. No SessionAuthentication, so the API never relies on
    # cookies and therefore needs no CSRF protection.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Secure by default: a view that forgets to declare permissions is locked, not open.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Never return unbounded lists. Phase 7 switches large lists to cursor pagination.
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
}

# --- JWT (SimpleJWT) ------------------------------------------------------------
SIMPLE_JWT = {
    # Short-lived: a stolen access token is only useful for minutes.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_TOKEN_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_TOKEN_DAYS", default=7)),
    # Every refresh returns a new refresh token and blacklists the old one, so a leaked
    # refresh token stops working as soon as the real client uses it once.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    # SIGNING_KEY defaults to SECRET_KEY: rotating SECRET_KEY logs everyone out.
}

# --- I18N / time --------------------------------------------------------------
LANGUAGE_CODE = "en-us"
# Store and compute in UTC; convert to local time only at the edges (UI, emails).
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files -------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Logging ------------------------------------------------------------------
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = build_logging_config(level=LOG_LEVEL, json_logs=env.bool("LOG_JSON", default=True))
