"""
Booking a seat safely when many people try to buy it at the same moment.

The race we must prevent ("check-then-act"):

    request A: SELECT seat 7 -> available
    request B: SELECT seat 7 -> available        <- both checks pass
    request A: UPDATE seat 7 -> booked; INSERT booking
    request B: UPDATE seat 7 -> booked; INSERT booking   <- seat sold twice

Two strategies, chosen by settings.BOOKING_LOCK_STRATEGY:

PESSIMISTIC (assume conflicts will happen; prevent them)
    SELECT ... FOR UPDATE locks the seat row until our transaction ends. B's SELECT
    blocks until A commits, then sees status=booked and gets a clean 409.
    + Simple to reason about, no retries.
    - Requests for the same seat queue up and hold a DB connection while waiting.

OPTIMISTIC (assume conflicts are rare; detect them)
    Read without locking, remember `version`, then
    UPDATE ... SET version = version + 1 WHERE id = 7 AND version = <what we read>.
    If 0 rows changed, someone else wrote first: re-read and decide again.
    + No waiting on locks; great when contention is low.
    - Losers do wasted work and retry; every writer must bump `version`.

Either way, the partial unique index booking_one_active_per_seat (Phase 2) is the
final guarantee: if this code ever had a bug, Postgres still refuses a second active
booking for the seat.
"""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.bookings.exceptions import (
    BookingNotCancellable,
    EventNotBookable,
    SeatContended,
    SeatUnavailable,
)
from apps.bookings.models import Booking
from apps.events.models import Event, Seat

logger = logging.getLogger(__name__)

PESSIMISTIC = "pessimistic"
OPTIMISTIC = "optimistic"


def book_seat(*, user, seat_id: int) -> Booking:
    """Entry point used by the API. Dispatches to the configured locking strategy."""
    strategy = settings.BOOKING_LOCK_STRATEGY
    if strategy == PESSIMISTIC:
        return book_seat_pessimistic(user=user, seat_id=seat_id)
    if strategy == OPTIMISTIC:
        return book_seat_optimistic(user=user, seat_id=seat_id)
    raise ValueError(f"Unknown BOOKING_LOCK_STRATEGY: {strategy!r}")


# --- Pessimistic ------------------------------------------------------------------------


@transaction.atomic
def book_seat_pessimistic(*, user, seat_id: int) -> Booking:
    try:
        seat = (
            Seat.objects.select_related("event")
            # FOR UPDATE OF <seat table> only. Without of=("self",), Postgres would also
            # lock the JOINed event row, and every booking for the event would queue
            # behind one lock even for different seats.
            .select_for_update(of=("self",))
            .get(pk=seat_id)
        )
    except Seat.DoesNotExist:
        raise NotFound("Seat not found.") from None

    # From here until COMMIT, no other transaction can lock, update or delete this seat.
    _ensure_bookable(seat)
    Seat.objects.filter(pk=seat.pk).update(status=Seat.Status.BOOKED, version=F("version") + 1)
    return _create_booking(user=user, seat=seat)


# --- Optimistic -------------------------------------------------------------------------


def book_seat_optimistic(*, user, seat_id: int) -> Booking:
    max_attempts = settings.BOOKING_OPTIMISTIC_MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        seat = _read_seat(seat_id)  # plain SELECT, no lock
        _ensure_bookable(seat)  # if someone already booked it, fail fast with 409

        with transaction.atomic():
            # The compare-and-swap. Postgres evaluates the WHERE against the latest
            # committed row (waiting briefly if another UPDATE on this row is in flight),
            # so only one of several concurrent writers can match version=<old>.
            updated = Seat.objects.filter(pk=seat.pk, version=seat.version).update(
                status=Seat.Status.BOOKED, version=F("version") + 1
            )
            if updated == 1:
                return _create_booking(user=user, seat=seat)

        # 0 rows: the seat changed since we read it (booked, repriced, ...). Loop and
        # re-read; usually the next read shows it's booked and we return a clean 409.
        logger.info(
            "optimistic booking conflict",
            extra={"seat_id": seat_id, "attempt": attempt, "read_version": seat.version},
        )

    raise SeatContended()


def _read_seat(seat_id: int) -> Seat:
    try:
        return Seat.objects.select_related("event").get(pk=seat_id)
    except Seat.DoesNotExist:
        raise NotFound("Seat not found.") from None


# --- Shared -----------------------------------------------------------------------------


def _ensure_bookable(seat: Seat) -> None:
    event = seat.event
    if event.status != Event.Status.PUBLISHED or event.starts_at <= timezone.now():
        raise EventNotBookable()
    if seat.status != Seat.Status.AVAILABLE:
        raise SeatUnavailable()


def _create_booking(*, user, seat: Seat) -> Booking:
    # Runs inside the caller's transaction, right after the seat UPDATE succeeded.
    try:
        with transaction.atomic():  # savepoint, so a failure here can be handled cleanly
            return Booking.objects.create(user=user, seat=seat, amount=seat.price)
    except IntegrityError:
        # Only reachable if the locking above is broken or some other code path booked
        # the seat without updating Seat.status. The DB index saved us; make it loud.
        logger.error("partial unique index blocked a double booking", extra={"seat_id": seat.pk})
        raise SeatUnavailable() from None


# --- Cancel -----------------------------------------------------------------------------


@transaction.atomic
def cancel_booking(*, booking: Booking) -> Booking:
    """
    Cancel a pending booking and free its seat.

    Locks the SEAT first, then the booking: the same order book_seat_pessimistic uses
    (seat, then the new booking row). Taking locks in one global order is what prevents
    deadlocks between a booking and a cancel touching the same seat.
    """
    seat = (
        Seat.objects.select_related("event").select_for_update(of=("self",)).get(pk=booking.seat_id)
    )
    booking = Booking.objects.select_for_update().get(pk=booking.pk)  # fresh, locked copy

    if booking.status == Booking.Status.CANCELLED:
        return booking  # idempotent: cancelling twice is not an error
    if booking.status != Booking.Status.PENDING:
        # Confirmed (paid) bookings need a refund flow: Phase 5.
        raise BookingNotCancellable("Paid bookings can't be cancelled yet.")
    if seat.event.starts_at <= timezone.now():
        raise BookingNotCancellable("The event has already started.")

    booking.status = Booking.Status.CANCELLED
    booking.save(update_fields=["status", "updated_at"])
    Seat.objects.filter(pk=seat.pk).update(status=Seat.Status.AVAILABLE, version=F("version") + 1)
    return booking
