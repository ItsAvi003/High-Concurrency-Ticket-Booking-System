"""
Real concurrency: many threads, each with its own Postgres connection and transaction,
all released at the same instant.

transaction=True is required. A normal django_db test wraps everything in one
transaction that is never committed, so other threads (other connections) couldn't see
the event and seats we create. transaction=True commits for real and truncates the
tables afterwards.
"""

import time
from collections import Counter

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.bookings import services
from apps.bookings.concurrency import run_in_parallel
from apps.bookings.models import Booking
from apps.bookings.services import OPTIMISTIC, PESSIMISTIC
from apps.events.models import Seat

URL = reverse("bookings:booking-list")

REQUESTS = 100
SEATS = 10


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("strategy", [PESSIMISTIC, OPTIMISTIC])
def test_100_parallel_requests_for_10_seats_sell_exactly_10(
    settings, strategy, make_event, make_venue, make_user, client_for
):
    settings.BOOKING_LOCK_STRATEGY = strategy
    event = make_event(venue=make_venue(rows=1, seats_per_row=SEATS))
    seat_ids = list(event.seats.values_list("pk", flat=True))
    # Prepare users and tokens before the race so the race measures only booking.
    clients = [client_for(make_user()) for _ in range(REQUESTS)]
    # 10 contenders per seat: request i wants seat i % 10.
    calls = [(clients[i], seat_ids[i % SEATS]) for i in range(REQUESTS)]

    def attempt(client, seat_id):
        response = client.post(URL, {"seat": seat_id})
        return response.status_code, response.json().get("detail")

    outcomes = run_in_parallel(attempt, calls)

    errors = [o.error for o in outcomes if o.error]
    assert errors == []  # no exceptions, so no 500s, no deadlocks, no IntegrityErrors
    statuses = Counter(status for status, _ in (o.value for o in outcomes))
    print(f"\n[{strategy}] {REQUESTS} requests / {SEATS} seats -> {dict(statuses)}")  # pytest -s
    assert statuses == {201: SEATS, 409: REQUESTS - SEATS}

    # The database agrees: exactly one active booking per seat, every seat sold.
    assert Booking.objects.count() == SEATS
    assert sorted(Booking.objects.values_list("seat_id", flat=True)) == sorted(seat_ids)
    assert set(Seat.objects.filter(event=event).values_list("status", flat=True)) == {
        Seat.Status.BOOKED
    }


def _naive_book(user, seat_id):
    """
    The BROKEN version, kept here only to prove the race is real.
    Check-then-act with no lock and no version check.
    """
    seat = Seat.objects.get(pk=seat_id)
    if seat.status != Seat.Status.AVAILABLE:
        return "saw it was taken"
    time.sleep(0.05)  # some work between check and write (e.g. a price lookup)
    with transaction.atomic():
        Seat.objects.filter(pk=seat_id).update(status=Seat.Status.BOOKED)
        try:
            with transaction.atomic():
                Booking.objects.create(user=user, seat=seat, amount=seat.price)
            return "booked"
        except IntegrityError:
            return "passed the check, blocked by the DB index"


@pytest.mark.django_db(transaction=True)
def test_naive_check_then_act_really_races(make_event, make_venue, make_user):
    seat = make_event(venue=make_venue(rows=1, seats_per_row=1)).seats.get()
    users = [make_user() for _ in range(20)]

    outcomes = run_in_parallel(_naive_book, [(user, seat.pk) for user in users])

    results = Counter(o.value for o in outcomes)
    print(f"\n[naive] 20 requests / 1 seat -> {dict(results)}")  # visible with pytest -s
    # Many requests saw "available" at the same time: the application logic is broken...
    assert results["passed the check, blocked by the DB index"] >= 1
    # ...and only the partial unique index from Phase 2 kept it to one sale.
    assert results["booked"] == 1
    assert Booking.objects.count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("strategy", [PESSIMISTIC, OPTIMISTIC])
def test_one_hot_seat_many_buyers(settings, strategy, make_event, make_venue, make_user):
    # Worst case for both strategies: 50 people, 1 seat. Calls the service directly.
    settings.BOOKING_LOCK_STRATEGY = strategy
    seat = make_event(venue=make_venue(rows=1, seats_per_row=1)).seats.get()
    users = [make_user() for _ in range(50)]

    outcomes = run_in_parallel(
        lambda user: services.book_seat(user=user, seat_id=seat.pk), [(u,) for u in users]
    )

    winners = [o for o in outcomes if o.error is None]
    losers = Counter(type(o.error).__name__ for o in outcomes if o.error is not None)
    print(f"\n[{strategy}] 50 requests / 1 seat -> 1 winner, losers {dict(losers)}")
    assert len(winners) == 1
    # Optimistic may report "contended" if it ran out of retries; both are clean 409s.
    assert set(losers) <= {"SeatUnavailable", "SeatContended"}
    assert sum(losers.values()) == 49
