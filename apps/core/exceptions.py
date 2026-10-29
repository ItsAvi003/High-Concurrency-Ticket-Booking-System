from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class Conflict(APIException):
    """409: the request is valid but clashes with the current state of the resource."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state of the resource."
    default_code = "conflict"


def api_exception_handler(exc, context):
    """
    DRF's default handler, plus: deleting a row that other rows still reference
    (on_delete=PROTECT) becomes a 409 instead of an unhandled 500.
    """
    if isinstance(exc, ProtectedError):
        exc = Conflict("This object is still referenced by other records and cannot be deleted.")
    return exception_handler(exc, context)
