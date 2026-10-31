"""
Deterministic tests of the locking logic. A "concurrent writer" is simulated by changing
the seat between the service's read and its write, so each branch runs every time.
"""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.models import F
from django.test.utils import CaptureQueriesContext

from apps.bookings import services
from apps.bookings.exceptions import SeatContended, SeatUnavailable
from apps.bookings.models import Booking
from apps.events.models import Seat
from apps.events.services import update_event

pytestmark = pytest.mark.django_db


@pytest.fixture
def seat(make_event):
    return make_event().seats.first()


def _interfere_after_reads(monkeypatch, interference, times=1):
    """
    Make the first `times` calls to services._read_seat run `interference(seat_id)` right
    after reading: exactly what a concurrent request committing in between would look like.
    Returns the list of versions the service read, one per attempt.
    """
    real_read = services._read_seat
    versions_read = []

    def read_then_interfere(seat_id):
        seat = real_read(seat_id)
        versions_read.append(seat.version)
        if len(versions_read) <= times:
            interference(seat_id)
        return seat

    monkeypatch.setattr(services, "_read_seat", read_then_interfere)
    return versions_read


# --- pessimistic -------------------------------------------------------------------------


def test_pessimistic_locks_only_the_seat_row(customer, seat):
    with CaptureQueriesContext(connection) as queries:
        services.book_seat_pessimistic(user=customer, seat_id=seat.pk)

    locking = [q["sql"] for q in queries.captured_queries if "FOR UPDATE" in q["sql"]]
    assert len(locking) == 1
    # FOR UPDATE OF "events_seat": the JOINed events_event row is read but NOT locked.
    assert locking[0].endswith('FOR UPDATE OF "events_seat"')


def test_pessimistic_books_and_bumps_version(customer, seat):
    booking = services.book_seat_pessimistic(user=customer, seat_id=seat.pk)

    seat.refresh_from_db()
    assert (seat.status, seat.version) == (Seat.Status.BOOKED, 1)
    assert booking.amount == seat.price


# --- optimistic --------------------------------------------------------------------------


def test_optimistic_retries_when_seat_changed_but_is_still_available(monkeypatch, customer, seat):
    # Someone repriced the seat between our read and our write: version moved on, seat
    # still free. The first UPDATE matches 0 rows, the retry reads the new price and wins.
    def reprice(seat_id):
        update_event(seat.event, price=Decimal("650.00"))

    versions_read = _interfere_after_reads(monkeypatch, reprice)

    booking = services.book_seat_optimistic(user=customer, seat_id=seat.pk)

    assert versions_read == [0, 1]  # two attempts
    assert booking.amount == Decimal("650.00")  # the fresh price, not the stale one


def test_optimistic_returns_409_when_someone_else_booked_in_between(
    monkeypatch, make_user, customer, seat
):
    rival = make_user()

    def rival_books(seat_id):
        services.book_seat_pessimistic(user=rival, seat_id=seat_id)

    versions_read = _interfere_after_reads(monkeypatch, rival_books)

    with pytest.raises(SeatUnavailable):
        services.book_seat_optimistic(user=customer, seat_id=seat.pk)

    assert versions_read == [0, 1]  # retried once, then saw "booked" and stopped
    assert list(Booking.objects.values_list("user", flat=True)) == [rival.pk]


def test_optimistic_gives_up_after_max_attempts(monkeypatch, settings, customer, seat):
    settings.BOOKING_OPTIMISTIC_MAX_ATTEMPTS = 3

    def touch(seat_id):
        Seat.objects.filter(pk=seat_id).update(version=F("version") + 1)

    versions_read = _interfere_after_reads(monkeypatch, touch, times=3)

    with pytest.raises(SeatContended):
        services.book_seat_optimistic(user=customer, seat_id=seat.pk)

    assert versions_read == [0, 1, 2]
    assert not Booking.objects.exists()
    seat.refresh_from_db()
    assert seat.status == Seat.Status.AVAILABLE


def test_optimistic_never_takes_a_row_lock_while_reading(customer, seat):
    with CaptureQueriesContext(connection) as queries:
        services.book_seat_optimistic(user=customer, seat_id=seat.pk)

    assert not any("FOR UPDATE" in q["sql"] for q in queries.captured_queries)
    update = next(q["sql"] for q in queries.captured_queries if q["sql"].startswith("UPDATE"))
    assert '"events_seat"."version" = 0' in update  # the compare-and-swap condition


# --- shared -------------------------------------------------------------------------------


def test_repricing_bumps_version_of_available_seats_only(make_event, customer):
    event = make_event()
    booked = event.seats.first()
    services.book_seat_pessimistic(user=customer, seat_id=booked.pk)

    update_event(event, price=Decimal("1.00"))

    booked.refresh_from_db()
    assert booked.version == 1  # booked seat untouched by repricing
    assert set(event.seats.exclude(pk=booked.pk).values_list("version", flat=True)) == {1}


def test_db_index_backstop_turns_double_booking_into_409(customer, make_user, seat):
    # Simulate a bug elsewhere: a booking exists but Seat.status was never updated.
    Booking.objects.create(user=make_user(), seat=seat, amount=seat.price)

    with pytest.raises(SeatUnavailable):
        services.book_seat_pessimistic(user=customer, seat_id=seat.pk)

    # The whole transaction rolled back, including the seat UPDATE.
    seat.refresh_from_db()
    assert (seat.status, seat.version) == (Seat.Status.AVAILABLE, 0)
    assert Booking.objects.count() == 1


def test_unknown_strategy_is_a_configuration_error(settings, customer, seat):
    settings.BOOKING_LOCK_STRATEGY = "yolo"

    with pytest.raises(ValueError, match="yolo"):
        services.book_seat(user=customer, seat_id=seat.pk)
