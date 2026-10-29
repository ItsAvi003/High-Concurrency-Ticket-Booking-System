"""The partial unique index: at most one active booking per seat."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.bookings.models import Booking
from apps.events.models import Event

pytestmark = pytest.mark.django_db


@pytest.fixture
def seat(make_event):
    return make_event().seats.first()


def _book(user, seat, status=Booking.Status.PENDING):
    return Booking.objects.create(user=user, seat=seat, status=status, amount=seat.price)


@pytest.mark.parametrize("second_status", [Booking.Status.PENDING, Booking.Status.CONFIRMED])
def test_second_active_booking_for_same_seat_is_rejected_by_postgres(
    make_user, seat, second_status
):
    _book(make_user(), seat, status=Booking.Status.CONFIRMED)

    with pytest.raises(IntegrityError, match="booking_one_active_per_seat"):
        _book(make_user(), seat, status=second_status)


def test_seat_can_be_rebooked_after_cancellation(make_user, seat):
    first = _book(make_user(), seat)
    first.status = Booking.Status.CANCELLED
    first.save()

    second = _book(make_user(), seat)  # no IntegrityError: cancelled rows are outside the index

    assert second.status == Booking.Status.PENDING
    assert seat.bookings.count() == 2


def test_many_cancelled_bookings_for_one_seat_are_allowed(make_user, seat):
    for _ in range(3):
        _book(make_user(), seat, status=Booking.Status.CANCELLED)

    assert seat.bookings.count() == 3


def test_amount_cannot_be_negative(make_user, seat):
    with pytest.raises(IntegrityError, match="booking_amount_non_negative"):
        Booking.objects.create(user=make_user(), seat=seat, amount=-1)


def test_event_with_bookings_cannot_be_deleted(make_user, seat):
    # Event -> Seat is CASCADE, but Seat <- Booking is PROTECT, so the whole delete is refused.
    _book(make_user(), seat)

    with pytest.raises(ProtectedError), transaction.atomic():
        seat.event.delete()

    assert Event.objects.filter(pk=seat.event_id).exists()


def test_user_with_bookings_cannot_be_deleted(make_user, seat):
    user = make_user()
    _book(user, seat)

    with pytest.raises(ProtectedError), transaction.atomic():
        user.delete()
