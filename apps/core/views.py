import logging

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.core import health

logger = logging.getLogger(__name__)


@require_GET
def liveness(request):
    """Is the process up and able to serve HTTP? Touches no dependencies."""
    return JsonResponse({"status": "ok"})


@require_GET
def readiness(request):
    """Can this instance do real work right now? Checks Postgres and Redis."""
    results = {}
    for name, check in health.READINESS_CHECKS.items():
        try:
            check()
            results[name] = "ok"
        except Exception:
            # Full error goes to logs; the public response only says "unavailable".
            logger.exception("readiness check failed: %s", name, extra={"check": name})
            results[name] = "unavailable"

    healthy = all(state == "ok" for state in results.values())
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable", "checks": results},
        status=200 if healthy else 503,
    )
