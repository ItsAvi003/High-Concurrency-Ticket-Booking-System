"""
Postgres isolation levels, demonstrated with two real transactions in a forced order:

    T1: BEGIN; read seat (available)
    T2: BEGIN; read seat (available)
    T1: UPDATE seat -> booked; COMMIT
    T2: UPDATE seat -> booked; ...?   <- what happens here depends on isolation level

READ COMMITTED (Postgres default): each statement sees data committed before *it*
started. T2's UPDATE simply overwrites T1's: a "lost update". T2 thinks it booked the
seat. This is why check-then-act is unsafe at the default level.

REPEATABLE READ: the whole transaction sees one snapshot. When T2 tries to update a row
that changed after its snapshot, Postgres aborts T2 with a serialization failure. Safe,
but the application must catch the error and retry the whole transaction.

The fix we actually use at READ COMMITTED: make the write conditional
(WHERE status = 'available' / WHERE version = N) or lock the row first.
"""

import threading

import pytest
from django.db import OperationalError, connection, transaction

from apps.events.models import Seat

WAIT = 10  # seconds; generous so a slow CI machine doesn't flake


def _set_isolation(level):
    # Must be the first statement of the transaction.
    with connection.cursor() as cursor:
        cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {level}")


def _interleave(seat_id, isolation, conditional_update):
    t1_has_read, t2_has_read, t1_committed = threading.Event(), threading.Event(), threading.Event()
    results = {}

    def book(**extra_filter):
        return Seat.objects.filter(pk=seat_id, **extra_filter).update(status=Seat.Status.BOOKED)

    condition = {"status": Seat.Status.AVAILABLE} if conditional_update else {}

    def transaction_1():
        try:
            with transaction.atomic():
                _set_isolation(isolation)
                Seat.objects.get(pk=seat_id)
                t1_has_read.set()
                t2_has_read.wait(WAIT)
                book(**condition)
            results["t1"] = "committed"
        finally:
            t1_committed.set()
            connection.close()

    def transaction_2():
        try:
            with transaction.atomic():
                _set_isolation(isolation)
                t1_has_read.wait(WAIT)
                results["t2_read"] = Seat.objects.get(pk=seat_id).status
                t2_has_read.set()
                t1_committed.wait(WAIT)
                results["t2_rows_updated"] = book(**condition)
        except OperationalError as exc:
            results["t2_error"] = type(exc.__cause__).__name__
        finally:
            connection.close()

    threads = [threading.Thread(target=transaction_1), threading.Thread(target=transaction_2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT * 2)
    return results


@pytest.fixture
def seat_id(make_event):
    return make_event().seats.first().pk


@pytest.mark.django_db(transaction=True)
def test_read_committed_allows_lost_update(seat_id):
    results = _interleave(seat_id, "READ COMMITTED", conditional_update=False)

    assert results["t1"] == "committed"
    assert results["t2_read"] == "available"  # T2's check passed...
    assert results["t2_rows_updated"] == 1  # ...and its write "succeeded" too. Seat sold twice.


@pytest.mark.django_db(transaction=True)
def test_read_committed_with_conditional_update_is_safe(seat_id):
    results = _interleave(seat_id, "READ COMMITTED", conditional_update=True)

    assert results["t2_read"] == "available"  # T2's stale check still passed...
    # ...but UPDATE ... WHERE status='available' re-checks the committed row: 0 rows.
    assert results["t2_rows_updated"] == 0


@pytest.mark.django_db(transaction=True)
def test_repeatable_read_aborts_the_second_writer(seat_id):
    results = _interleave(seat_id, "REPEATABLE READ", conditional_update=False)

    assert results["t1"] == "committed"
    assert results["t2_read"] == "available"
    assert results["t2_error"] == "SerializationFailure"  # "could not serialize access..."
    assert "t2_rows_updated" not in results
