"""Booking API behaviour. Every test runs once per locking strategy."""

from datetime import timedelta

import pytest
from django.urls import reverse

from apps.bookings.models import Booking
from apps.bookings.services import OPTIMISTIC, PESSIMISTIC
from apps.events.models import Event, Seat

pytestmark = pytest.mark.django_db

LIST_URL = reverse("bookings:booking-list")


@pytest.fixture(autouse=True, params=[PESSIMISTIC, OPTIMISTIC])
def strategy(request, settings):
    settings.BOOKING_LOCK_STRATEGY = request.param
    return request.param


def detail_url(booking):
    return reverse("bookings:booking-detail", kwargs={"pk": booking.pk})


def cancel_url(booking):
    return reverse("bookings:booking-cancel", kwargs={"pk": booking.pk})


@pytest.fixture
def seat(make_event):
    return make_event().seats.order_by("row_number", "number").first()


def _book(client, seat):
    return client.post(LIST_URL, {"seat": seat.pk})


# --- create ----------------------------------------------------------------------------


def test_anonymous_cannot_book(api_client, seat):
    assert _book(api_client, seat).status_code == 401


def test_booking_an_available_seat(client_for, customer, seat):
    response = _book(client_for(customer), seat)

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "pending"
    assert body["amount"] == "499.00"
    assert body["seat"] == {"id": seat.pk, "row": "A", "number": 1}
    assert body["event"]["id"] == seat.event_id

    seat.refresh_from_db()
    assert seat.status == Seat.Status.BOOKED
    assert seat.version == 1
    assert Booking.objects.get(pk=body["id"]).user == customer


def test_booking_a_taken_seat_is_409(client_for, make_user, seat):
    assert _book(client_for(make_user()), seat).status_code == 201

    response = _book(client_for(make_user()), seat)

    assert response.status_code == 409
    assert response.json()["detail"] == "This seat is no longer available."
    assert Booking.objects.count() == 1


def test_booking_missing_seat_is_404(client_for, customer):
    assert client_for(customer).post(LIST_URL, {"seat": 999_999}).status_code == 404


@pytest.mark.parametrize("payload", [{}, {"seat": "abc"}, {"seat": 0}, {"seat": -3}])
def test_invalid_payload_is_400(client_for, customer, payload):
    response = client_for(customer).post(LIST_URL, payload)

    assert response.status_code == 400
    assert "seat" in response.json()


@pytest.mark.parametrize(
    ("event_kwargs"),
    [
        {"status": Event.Status.DRAFT},
        {"status": Event.Status.CANCELLED},
        {"starts_in": -timedelta(hours=1)},  # published but already started
    ],
)
def test_unbookable_event_is_400(client_for, customer, make_event, event_kwargs):
    seat = make_event(**event_kwargs).seats.first()

    response = _book(client_for(customer), seat)

    assert response.status_code == 400
    assert response.json()["detail"] == "This event is not open for booking."
    seat.refresh_from_db()
    assert seat.status == Seat.Status.AVAILABLE


def test_amount_is_the_price_at_booking_time(client_for, customer, seat):
    booking_id = _book(client_for(customer), seat).json()["id"]
    Seat.objects.filter(pk=seat.pk).update(price="999.00")

    assert str(Booking.objects.get(pk=booking_id).amount) == "499.00"


# --- read ------------------------------------------------------------------------------


def test_users_see_only_their_own_bookings(client_for, make_user, make_event):
    event = make_event()
    seat_a, seat_b = event.seats.all()[:2]
    alice, bob = make_user(), make_user()
    alice_booking = _book(client_for(alice), seat_a).json()
    _book(client_for(bob), seat_b)

    results = client_for(alice).get(LIST_URL).json()["results"]

    assert [b["id"] for b in results] == [alice_booking["id"]]


def test_other_users_booking_is_404(client_for, make_user, seat):
    booking = Booking.objects.get(pk=_book(client_for(make_user()), seat).json()["id"])

    assert client_for(make_user()).get(detail_url(booking)).status_code == 404


def test_admin_sees_all_bookings(client_for, platform_admin, make_user, seat):
    booking_id = _book(client_for(make_user()), seat).json()["id"]

    results = client_for(platform_admin).get(LIST_URL).json()["results"]

    assert [b["id"] for b in results] == [booking_id]


def test_booking_list_has_no_n_plus_one(
    client_for, customer, make_event, django_assert_num_queries
):
    client = client_for(customer)
    for seat in make_event().seats.all()[:6]:
        _book(client, seat)

    # 1 user lookup (JWT auth) + 1 COUNT for pagination + 1 page query with JOINs.
    with django_assert_num_queries(3):
        response = client.get(LIST_URL)

    assert response.json()["count"] == 6


def test_bookings_cannot_be_edited_or_deleted_directly(client_for, customer, seat):
    client = client_for(customer)
    booking = Booking.objects.get(pk=_book(client, seat).json()["id"])

    assert client.patch(detail_url(booking), {"status": "confirmed"}).status_code == 405
    assert client.delete(detail_url(booking)).status_code == 405


# --- cancel ----------------------------------------------------------------------------


def test_cancel_frees_the_seat_for_someone_else(client_for, make_user, seat):
    owner, next_buyer = make_user(), make_user()
    booking = Booking.objects.get(pk=_book(client_for(owner), seat).json()["id"])

    response = client_for(owner).post(cancel_url(booking))

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    seat.refresh_from_db()
    assert seat.status == Seat.Status.AVAILABLE
    assert seat.version == 2  # booked (+1), cancelled (+1)
    assert _book(client_for(next_buyer), seat).status_code == 201


def test_cancel_is_idempotent(client_for, customer, seat):
    client = client_for(customer)
    booking = Booking.objects.get(pk=_book(client, seat).json()["id"])

    assert client.post(cancel_url(booking)).status_code == 200
    assert client.post(cancel_url(booking)).status_code == 200
    seat.refresh_from_db()
    assert seat.version == 2  # the second cancel changed nothing


def test_cannot_cancel_someone_elses_booking(client_for, make_user, seat):
    booking = Booking.objects.get(pk=_book(client_for(make_user()), seat).json()["id"])

    assert client_for(make_user()).post(cancel_url(booking)).status_code == 404
    booking.refresh_from_db()
    assert booking.status == Booking.Status.PENDING


def test_admin_can_cancel_any_booking(client_for, platform_admin, make_user, seat):
    booking = Booking.objects.get(pk=_book(client_for(make_user()), seat).json()["id"])

    assert client_for(platform_admin).post(cancel_url(booking)).status_code == 200


def test_confirmed_booking_cannot_be_cancelled_yet(client_for, customer, seat):
    client = client_for(customer)
    booking = Booking.objects.get(pk=_book(client, seat).json()["id"])
    Booking.objects.filter(pk=booking.pk).update(status=Booking.Status.CONFIRMED)

    response = client.post(cancel_url(booking))

    assert response.status_code == 409
    seat.refresh_from_db()
    assert seat.status == Seat.Status.BOOKED
