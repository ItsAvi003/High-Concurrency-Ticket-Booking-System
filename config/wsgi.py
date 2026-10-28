import os

from django.core.wsgi import get_wsgi_application

# WSGI is only used by gunicorn in deployed environments, so default to prod.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
