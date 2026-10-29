"""
Venue -> Event -> Seat.

A Venue stores only its layout (rows x seats_per_row). Creating an Event generates one
Seat row per physical seat for that event (apps/events/services.py). Those per-event
Seat rows are the inventory that booking locks in Phase 3.

Business rules that must never be violated are enforced by Postgres constraints, not
only by serializers: any code path (admin, shell, a future bug) is still protected.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel

MAX_ROWS = 100
MAX_SEATS_PER_ROW = 200


def row_label(row_number: int) -> str:
    """1 -> "A", 26 -> "Z", 27 -> "AA", 28 -> "AB" (spreadsheet-style column names)."""
    if row_number < 1:
        raise ValueError("row_number starts at 1")
    label = ""
    while row_number:
        row_number, remainder = divmod(row_number - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


class Venue(TimeStampedModel):
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=100)
    address = models.CharField(max_length=300, blank=True)
    rows = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(MAX_ROWS)]
    )
    seats_per_row = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(MAX_SEATS_PER_ROW)]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "city"], name="venue_unique_name_per_city"),
            models.CheckConstraint(
                condition=Q(rows__gte=1, rows__lte=MAX_ROWS), name="venue_rows_in_range"
            ),
            models.CheckConstraint(
                condition=Q(seats_per_row__gte=1, seats_per_row__lte=MAX_SEATS_PER_ROW),
                name="venue_seats_per_row_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.name}, {self.city}"

    @property
    def capacity(self) -> int:
        return self.rows * self.seats_per_row


class EventQuerySet(models.QuerySet):
    def publicly_visible(self):
        """What anonymous visitors may see: published events that haven't started yet."""
        return self.filter(status=Event.Status.PUBLISHED, starts_at__gt=timezone.now())

    def with_seat_counts(self):
        """
        Add total_seats / available_seats in the same SQL query (COUNT ... GROUP BY),
        instead of running two extra COUNT queries per event while serializing.
        """
        return self.annotate(
            total_seats=Count("seats"),
            available_seats=Count("seats", filter=Q(seats__status=Seat.Status.AVAILABLE)),
        )


class Event(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"  # only the organizer can see it
        PUBLISHED = "published", "Published"  # visible to the public, bookable
        CANCELLED = "cancelled", "Cancelled"  # terminal

    # Which status changes are legal. Anything not listed here is rejected.
    ALLOWED_TRANSITIONS = {
        Status.DRAFT: {Status.PUBLISHED, Status.CANCELLED},
        Status.PUBLISHED: {Status.CANCELLED},
        Status.CANCELLED: set(),
    }

    # PROTECT: deleting a user or venue must never silently delete their events.
    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organized_events",
        limit_choices_to={"role__in": ["organizer", "admin"]},  # admin form dropdown only
    )
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="events")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    # Decimal, never float: 0.1 + 0.2 != 0.3 in floating point, and money must be exact.
    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    objects = EventQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="event_ends_after_start"
            ),
            models.CheckConstraint(condition=Q(price__gte=0), name="event_price_non_negative"),
        ]

    def __str__(self):
        return self.title

    def can_transition_to(self, new_status: str) -> bool:
        return new_status == self.status or new_status in self.ALLOWED_TRANSITIONS[self.status]


class Seat(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BOOKED = "booked", "Booked"

    # CASCADE: seats have no meaning without their event. Bookings PROTECT seats, so an
    # event with bookings still can't be deleted (see apps/bookings/models.py).
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="seats")
    # Stored as a number so ORDER BY row_number sorts A, B, ..., Z, AA correctly.
    # As text, "AA" would sort before "B".
    row_number = models.PositiveSmallIntegerField()
    number = models.PositiveSmallIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        constraints = [
            # Also creates an index on (event_id, row_number, number); its leading
            # event_id column serves "all seats of event X" lookups.
            models.UniqueConstraint(
                fields=["event", "row_number", "number"], name="seat_unique_position_per_event"
            ),
            models.CheckConstraint(
                condition=Q(row_number__gte=1, number__gte=1), name="seat_position_positive"
            ),
            models.CheckConstraint(condition=Q(price__gte=0), name="seat_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.event_id}:{self.row_label}{self.number}"

    @property
    def row_label(self) -> str:
        return row_label(self.row_number)
