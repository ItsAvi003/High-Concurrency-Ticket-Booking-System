"""
Write operations for events. Views and serializers call these instead of touching
several models themselves, so multi-step changes live in one transactional place.
"""

from django.db import transaction

from apps.events.models import Event, Seat

SEAT_INSERT_BATCH_SIZE = 1000


@transaction.atomic
def create_event_with_seats(*, organizer, venue, price, **fields) -> Event:
    """
    Create the event and one Seat per position in the venue layout.

    Atomic: if seat generation fails halfway, the event row is rolled back too, so we
    never end up with an event that has only some of its seats.
    """
    event = Event.objects.create(organizer=organizer, venue=venue, price=price, **fields)
    seats = [
        Seat(event=event, row_number=row, number=number, price=price)
        for row in range(1, venue.rows + 1)
        for number in range(1, venue.seats_per_row + 1)
    ]
    # One INSERT per 1000 rows instead of one per seat (a 20,000-seat venue would
    # otherwise mean 20,000 round trips to Postgres).
    Seat.objects.bulk_create(seats, batch_size=SEAT_INSERT_BATCH_SIZE)
    return event


@transaction.atomic
def update_event(event: Event, **changes) -> Event:
    """
    Apply changes. A new price applies to seats that are still available; booked seats
    keep their price, and the Booking row stores the amount actually charged.
    """
    price_changed = "price" in changes and changes["price"] != event.price
    for field, value in changes.items():
        setattr(event, field, value)
    event.save()
    if price_changed:
        event.seats.filter(status=Seat.Status.AVAILABLE).update(price=event.price)
    return event
