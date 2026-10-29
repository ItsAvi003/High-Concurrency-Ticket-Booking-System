"""Database constraints and model helpers. IntegrityError here means Postgres itself said no."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import F, ProtectedError
from django.utils import timezone

from apps.events.models import Event, Seat, Venue, row_label
from apps.events.services import create_event_with_seats, update_event

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("row_number", "label"), [(1, "A"), (2, "B"), (26, "Z"), (27, "AA"), (28, "AB"), (52, "AZ")]
)
def test_row_label(row_number, label):
    assert row_label(row_number) == label


def test_row_label_rejects_zero():
    with pytest.raises(ValueError):
        row_label(0)


def test_creating_event_generates_one_seat_per_position(make_event, make_venue):
    event = make_event(venue=make_venue(rows=2, seats_per_row=3), price=Decimal("250.00"))

    seats = list(event.seats.order_by("row_number", "number"))
    assert [(s.row_label, s.number) for s in seats] == [
        ("A", 1), ("A", 2), ("A", 3), ("B", 1), ("B", 2), ("B", 3),
    ]  # fmt: skip
    assert {s.price for s in seats} == {Decimal("250.00")}
    assert {s.status for s in seats} == {Seat.Status.AVAILABLE}


def test_seat_generation_is_atomic(make_user, make_venue, monkeypatch):
    # If seat insertion fails, the event row must be rolled back too.
    def exploding_bulk_create(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Seat.objects, "bulk_create", exploding_bulk_create)
    starts_at = timezone.now() + timedelta(days=1)

    with pytest.raises(RuntimeError):
        create_event_with_seats(
            organizer=make_user(role="organizer"),
            venue=make_venue(),
            title="Doomed",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2),
            price=Decimal("1.00"),
        )

    assert not Event.objects.filter(title="Doomed").exists()


def test_event_must_end_after_it_starts(make_event):
    event = make_event()

    with pytest.raises(IntegrityError, match="event_ends_after_start"):
        Event.objects.filter(pk=event.pk).update(ends_at=F("starts_at") - timedelta(minutes=1))


def test_event_price_cannot_be_negative(make_event):
    event = make_event()

    with pytest.raises(IntegrityError, match="event_price_non_negative"):
        Event.objects.filter(pk=event.pk).update(price=Decimal("-1"))


def test_seat_position_is_unique_per_event(make_event):
    event = make_event()
    seat = event.seats.first()

    with pytest.raises(IntegrityError, match="seat_unique_position_per_event"):
        Seat.objects.create(
            event=event, row_number=seat.row_number, number=seat.number, price=seat.price
        )


@pytest.mark.parametrize(("rows", "seats_per_row"), [(0, 5), (5, 0), (101, 5), (5, 201)])
def test_venue_layout_must_be_in_range(make_venue, rows, seats_per_row):
    with pytest.raises(IntegrityError):
        make_venue(rows=rows, seats_per_row=seats_per_row)


def test_venue_name_unique_per_city(make_venue):
    make_venue(name="Arena", city="Pune")
    make_venue(name="Arena", city="Mumbai")  # same name, different city: fine

    with pytest.raises(IntegrityError, match="venue_unique_name_per_city"):
        make_venue(name="Arena", city="Pune")


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (Event.Status.DRAFT, Event.Status.PUBLISHED, True),
        (Event.Status.DRAFT, Event.Status.CANCELLED, True),
        (Event.Status.PUBLISHED, Event.Status.CANCELLED, True),
        (Event.Status.PUBLISHED, Event.Status.DRAFT, False),
        (Event.Status.CANCELLED, Event.Status.PUBLISHED, False),
        (Event.Status.CANCELLED, Event.Status.DRAFT, False),
        (Event.Status.PUBLISHED, Event.Status.PUBLISHED, True),  # no-op is fine
    ],
)
def test_status_transitions(current, target, allowed):
    assert Event(status=current).can_transition_to(target) is allowed


def test_price_change_only_reprices_available_seats(make_event):
    event = make_event(price=Decimal("100.00"))
    booked = event.seats.first()
    booked.status = Seat.Status.BOOKED
    booked.save()

    update_event(event, price=Decimal("150.00"))

    booked.refresh_from_db()
    assert booked.price == Decimal("100.00")
    assert set(
        event.seats.filter(status=Seat.Status.AVAILABLE).values_list("price", flat=True)
    ) == {Decimal("150.00")}


def test_deleting_venue_with_events_is_blocked(make_event):
    event = make_event()

    with pytest.raises(ProtectedError), transaction.atomic():
        Venue.objects.filter(pk=event.venue_id).delete()
