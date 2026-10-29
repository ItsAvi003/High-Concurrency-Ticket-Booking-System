"""
Booking: one user holding one seat.

The booking endpoint arrives in Phase 3. The model exists now so its constraints are
designed together with Event and Seat.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.events.models import Seat


class Booking(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"  # payment flow arrives in Phase 5
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    # Statuses that occupy the seat. A cancelled booking frees it for someone else.
    ACTIVE_STATUSES = (Status.PENDING, Status.CONFIRMED)

    # PROTECT on both: bookings are financial records and must never disappear because
    # a user, seat or (via seat CASCADE) event was deleted.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings"
    )
    seat = models.ForeignKey(Seat, on_delete=models.PROTECT, related_name="bookings")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Copied from seat.price at booking time, so later price changes don't rewrite history.
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            # Partial unique index: at most one *active* booking per seat.
            # SQL: CREATE UNIQUE INDEX ... ON bookings_booking (seat_id)
            #      WHERE status IN ('pending', 'confirmed')
            # Cancelled bookings are outside the index, so a seat can be re-booked.
            # This is the last line of defence against double-selling a seat, even if the
            # application-level locking in Phase 3 had a bug.
            models.UniqueConstraint(
                fields=["seat"],
                condition=Q(status__in=["pending", "confirmed"]),
                name="booking_one_active_per_seat",
            ),
            models.CheckConstraint(condition=Q(amount__gte=0), name="booking_amount_non_negative"),
        ]

    def __str__(self):
        return f"Booking {self.pk} ({self.status})"
