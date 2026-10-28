import logging
import re
import time
import uuid

from apps.core.logging import request_id_var

logger = logging.getLogger("apps.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Accept an upstream id (e.g. from Nginx or a client) only if it looks sane, so nobody
# can inject newlines or megabytes of junk into our logs through a header.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-_.]{1,64}$")


class RequestIdMiddleware:
    """
    Give every request an id, expose it in logs and the response header,
    and write one structured access-log line per request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        # Not reset here: Django logs 4xx/5xx responses *after* the middleware chain returns,
        # and those lines need the id too. apps.core.logging resets it on request_finished.
        request_id_var.set(request_id)
        started = time.perf_counter()

        response = self.get_response(request)

        response[REQUEST_ID_HEADER] = request_id
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "%s %s %s %sms",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
