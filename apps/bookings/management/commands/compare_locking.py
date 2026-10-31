"""
Benchmark pessimistic vs optimistic seat locking under different levels of contention.

    docker compose run --rm web python manage.py compare_locking --requests 100

Creates throwaway users/venues/events (names prefixed "bench-"), fires the requests in
parallel threads straight at the booking service (no HTTP, so we measure locking, not
JSON or auth), prints a table, and deletes everything it created.
"""

import logging
import statistics
import time
import uuid
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings import services
from apps.bookings.concurrency import run_in_parallel
from apps.bookings.models import Booking
from apps.events.models import Event, Venue
from apps.events.services import create_event_with_seats


class _CountConflicts(logging.Handler):
    """Counts the 'optimistic booking conflict' log lines, i.e. wasted attempts."""

    def __init__(self):
        super().__init__()
        self.count = 0

    def emit(self, record):
        if record.getMessage() == "optimistic booking conflict":
            self.count += 1


class Command(BaseCommand):
    help = "Compare pessimistic and optimistic locking for seat booking."

    def add_arguments(self, parser):
        parser.add_argument("--requests", type=int, default=100)
        parser.add_argument("--rounds", type=int, default=3, help="Repeat and take the median.")

    def handle(self, *args, requests, rounds, **options):
        run_id = uuid.uuid4().hex[:8]
        users = self._make_users(run_id, requests)
        organizer = users[0]
        scenarios = [
            ("hot seat", 1),  # everyone wants the same seat
            ("10 seats", 10),  # the spec's scenario: 10 contenders per seat
            ("no contention", requests),  # everyone wants a different seat
        ]
        rows = []
        try:
            for scenario, seat_count in scenarios:
                for strategy in (services.PESSIMISTIC, services.OPTIMISTIC):
                    results = [
                        self._run_round(run_id, organizer, users, strategy, seat_count)
                        for _ in range(rounds)
                    ]
                    rows.append((scenario, strategy, self._median_of(results)))
        finally:
            self._cleanup(run_id)

        self._print_table(requests, rounds, rows)

    # --- one round -----------------------------------------------------------------

    def _run_round(self, run_id, organizer, users, strategy, seat_count):
        venue = Venue.objects.create(
            name=f"bench-{run_id}-{uuid.uuid4().hex[:6]}", city="Bench", rows=1,
            seats_per_row=seat_count,
        )  # fmt: skip
        starts_at = timezone.now() + timedelta(days=30)
        event = create_event_with_seats(
            organizer=organizer, venue=venue, title=f"bench-{run_id}", starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2), price=Decimal("100.00"),
            status=Event.Status.PUBLISHED,
        )  # fmt: skip
        seat_ids = list(event.seats.values_list("pk", flat=True))
        book = (
            services.book_seat_pessimistic
            if strategy == services.PESSIMISTIC
            else services.book_seat_optimistic
        )
        calls = [(user, seat_ids[i % seat_count]) for i, user in enumerate(users)]

        conflicts = _CountConflicts()
        service_logger = logging.getLogger(services.__name__)
        service_logger.addHandler(conflicts)
        service_logger.setLevel(logging.INFO)
        service_logger.propagate = False  # count conflict lines, don't print them
        started = time.perf_counter()
        try:
            outcomes = run_in_parallel(lambda u, s: book(user=u, seat_id=s), calls)
        finally:
            wall = time.perf_counter() - started
            service_logger.removeHandler(conflicts)
            service_logger.propagate = True

        latencies_ms = sorted(o.seconds * 1000 for o in outcomes)
        return {
            "booked": sum(1 for o in outcomes if o.error is None),
            "rejected": Counter(type(o.error).__name__ for o in outcomes if o.error),
            "retries": conflicts.count,
            "wall_ms": wall * 1000,
            "p50_ms": statistics.median(latencies_ms),
            "p95_ms": latencies_ms[int(len(latencies_ms) * 0.95) - 1],
            "max_ms": latencies_ms[-1],
        }

    @staticmethod
    def _median_of(results):
        merged = {"booked": results[0]["booked"], "rejected": results[0]["rejected"]}
        for key in ("retries", "wall_ms", "p50_ms", "p95_ms", "max_ms"):
            merged[key] = statistics.median(r[key] for r in results)
        return merged

    # --- setup / teardown ---------------------------------------------------------------

    @staticmethod
    def _make_users(run_id, count):
        users = [
            User(email=f"bench-{run_id}-{i}@example.com", role=User.Role.ORGANIZER)
            for i in range(count)
        ]
        for user in users:
            user.set_unusable_password()
        return User.objects.bulk_create(users)

    @staticmethod
    def _cleanup(run_id):
        # Order matters: bookings PROTECT seats and users, events PROTECT venues/organizers.
        Booking.objects.filter(user__email__startswith=f"bench-{run_id}-").delete()
        Event.objects.filter(title=f"bench-{run_id}").delete()  # cascades to seats
        Venue.objects.filter(name__startswith=f"bench-{run_id}-").delete()
        User.objects.filter(email__startswith=f"bench-{run_id}-").delete()

    # --- output ---------------------------------------------------------------------------

    def _print_table(self, requests, rounds, rows):
        self.stdout.write(f"\n{requests} parallel requests per round, median of {rounds} rounds\n")
        header = (
            f"{'scenario':<14} {'strategy':<12} {'booked':>6} {'409s':>5} {'retries':>7} "
            f"{'wall ms':>8} {'p50 ms':>7} {'p95 ms':>7} {'max ms':>7}"
        )
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for scenario, strategy, r in rows:
            self.stdout.write(
                f"{scenario:<14} {strategy:<12} {r['booked']:>6} "
                f"{sum(r['rejected'].values()):>5} {r['retries']:>7.0f} {r['wall_ms']:>8.0f} "
                f"{r['p50_ms']:>7.1f} {r['p95_ms']:>7.1f} {r['max_ms']:>7.1f}"
            )
