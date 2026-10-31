from rest_framework import status
from rest_framework.exceptions import APIException

from apps.core.exceptions import Conflict


class SeatUnavailable(Conflict):
    default_detail = "This seat is no longer available."
    default_code = "seat_unavailable"


class SeatContended(Conflict):
    """Optimistic locking gave up: the seat kept changing under us. The client may retry."""

    default_detail = "This seat is in high demand right now. Please try again."
    default_code = "seat_contended"


class EventNotBookable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This event is not open for booking."
    default_code = "event_not_bookable"


class BookingNotCancellable(Conflict):
    default_detail = "This booking can no longer be cancelled."
    default_code = "booking_not_cancellable"
