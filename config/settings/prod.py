from .base import *  # noqa: F403
from .base import env

DEBUG = False

# --- HTTPS hardening ------------------------------------------------------------
# Nginx terminates TLS and forwards plain HTTP; this header tells Django the original
# request was HTTPS. Only safe because Nginx overwrites the header from clients.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# Internal probes hit the container directly over HTTP; don't redirect them.
SECURE_REDIRECT_EXEMPT = [r"^health/"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # opt-in only once the domain is final; it is hard to undo
SECURE_CONTENT_TYPE_NOSNIFF = True
