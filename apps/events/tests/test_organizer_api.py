from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import Booking
from apps.events.models import Event, Seat

pytestmark = pytest.mark.django_db

LIST_URL = reverse("events:organizer-event-list")


def detail_url(event):
    return reverse("events:organizer-event-detail", kwargs={"pk": event.pk})


@pytest.fixture
def new_event_payload(make_venue):
    starts_at = timezone.now() + timedelta(days=30)
    return {
        "title": "Rock Night",
        "description": "Loud.",
        "venue": make_venue(rows=4, seats_per_row=5).pk,
        "starts_at": starts_at.isoformat(),
        "ends_at": (starts_at + timedelta(hours=3)).isoformat(),
        "price": "799.00",
    }


# --- who may use the organizer API ---------------------------------------------------


def test_anonymous_gets_401(api_client):
    assert api_client.get(LIST_URL).status_code == 401


def test_plain_user_gets_403(client_for, customer, new_event_payload):
    client = client_for(customer)

    assert client.get(LIST_URL).status_code == 403
    assert client.post(LIST_URL, new_event_payload).status_code == 403


# --- create ----------------------------------------------------------------------------


def test_organizer_creates_draft_event_with_generated_seats(
    client_for, organizer, new_event_payload
):
    response = client_for(organizer).post(LIST_URL, new_event_payload)

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "draft"
    assert (body["total_seats"], body["available_seats"]) == (20, 20)
    event = Event.objects.get(pk=body["id"])
    assert event.organizer == organizer
    assert event.seats.count() == 20


def test_organizer_field_in_body_is_ignored(client_for, organizer, make_user, new_event_payload):
    someone_else = make_user(role="organizer")

    response = client_for(organizer).post(
        LIST_URL, {**new_event_payload, "organizer": someone_else.pk}
    )

    assert Event.objects.get(pk=response.json()["id"]).organizer == organizer


def test_cannot_create_event_as_published(client_for, organizer, new_event_payload):
    response = client_for(organizer).post(LIST_URL, {**new_event_payload, "status": "published"})

    assert response.status_code == 400
    assert "status" in response.json()


def test_cannot_create_event_in_the_past(client_for, organizer, new_event_payload):
    past = timezone.now() - timedelta(days=1)
    payload = {
        **new_event_payload,
        "starts_at": past.isoformat(),
        "ends_at": (past + timedelta(hours=2)).isoformat(),
    }

    response = client_for(organizer).post(LIST_URL, payload)

    assert response.status_code == 400
    assert "starts_at" in response.json()


def test_end_before_start_is_400_not_500(client_for, organizer, new_event_payload):
    payload = {**new_event_payload, "ends_at": new_event_payload["starts_at"]}

    response = client_for(organizer).post(LIST_URL, payload)

    assert response.status_code == 400
    assert "ends_at" in response.json()


def test_negative_price_is_400(client_for, organizer, new_event_payload):
    response = client_for(organizer).post(LIST_URL, {**new_event_payload, "price": "-5.00"})

    assert response.status_code == 400
    assert "price" in response.json()


# --- read / ownership ------------------------------------------------------------------


def test_organizer_sees_only_own_events(client_for, organizer, make_event):
    mine = make_event(organizer=organizer, status=Event.Status.DRAFT)
    make_event()  # another organizer's

    response = client_for(organizer).get(LIST_URL)

    assert [item["id"] for item in response.json()["results"]] == [mine.pk]


def test_other_organizers_event_is_404_not_403(client_for, organizer, make_event):
    theirs = make_event()
    client = client_for(organizer)

    assert client.get(detail_url(theirs)).status_code == 404
    assert client.patch(detail_url(theirs), {"title": "hijacked"}).status_code == 404
    assert client.delete(detail_url(theirs)).status_code == 404
    theirs.refresh_from_db()
    assert theirs.title != "hijacked"


def test_admin_sees_and_edits_every_event(client_for, platform_admin, make_event):
    event = make_event(status=Event.Status.DRAFT)
    client = client_for(platform_admin)

    assert event.pk in [item["id"] for item in client.get(LIST_URL).json()["results"]]
    assert client.patch(detail_url(event), {"title": "Fixed by admin"}).status_code == 200


# --- update ----------------------------------------------------------------------------


def test_organizer_publishes_draft(client_for, organizer, make_event):
    event = make_event(organizer=organizer, status=Event.Status.DRAFT)

    response = client_for(organizer).patch(detail_url(event), {"status": "published"})

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert response.json()["total_seats"] == 12  # annotations present after update


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (Event.Status.PUBLISHED, "draft"),
        (Event.Status.CANCELLED, "published"),
    ],
)
def test_illegal_status_transitions_are_400(client_for, organizer, make_event, start, target):
    event = make_event(organizer=organizer, status=start)

    response = client_for(organizer).patch(detail_url(event), {"status": target})

    assert response.status_code == 400
    event.refresh_from_db()
    assert event.status == start


def test_cannot_publish_event_that_already_started(client_for, organizer, make_event):
    event = make_event(
        organizer=organizer, status=Event.Status.DRAFT, starts_in=-timedelta(hours=1)
    )

    response = client_for(organizer).patch(detail_url(event), {"status": "published"})

    assert response.status_code == 400


def test_cancelled_event_cannot_be_edited(client_for, organizer, make_event):
    event = make_event(organizer=organizer, status=Event.Status.CANCELLED)

    response = client_for(organizer).patch(detail_url(event), {"title": "Back from the dead"})

    assert response.status_code == 400


def test_venue_cannot_be_changed(client_for, organizer, make_event, make_venue):
    event = make_event(organizer=organizer, status=Event.Status.DRAFT)

    response = client_for(organizer).patch(detail_url(event), {"venue": make_venue().pk})

    assert response.status_code == 400
    assert "venue" in response.json()


def test_patch_with_only_ends_at_is_validated_against_existing_start(
    client_for, organizer, make_event
):
    event = make_event(organizer=organizer, status=Event.Status.DRAFT)
    too_early = (event.starts_at - timedelta(minutes=1)).isoformat()

    response = client_for(organizer).patch(detail_url(event), {"ends_at": too_early})

    assert response.status_code == 400
    assert "ends_at" in response.json()


def test_price_update_reprices_available_seats(client_for, organizer, make_event):
    event = make_event(organizer=organizer, price=Decimal("100.00"))

    client_for(organizer).patch(detail_url(event), {"price": "120.00"})

    assert set(event.seats.values_list("price", flat=True)) == {Decimal("120.00")}


# --- delete ------------------------------------------------------------------------------


def test_draft_can_be_deleted_with_its_seats(client_for, organizer, make_event):
    event = make_event(organizer=organizer, status=Event.Status.DRAFT)

    response = client_for(organizer).delete(detail_url(event))

    assert response.status_code == 204
    assert not Event.objects.filter(pk=event.pk).exists()
    assert not Seat.objects.filter(event_id=event.pk).exists()


def test_published_event_cannot_be_deleted(client_for, organizer, make_event):
    event = make_event(organizer=organizer)

    response = client_for(organizer).delete(detail_url(event))

    assert response.status_code == 409
    assert Event.objects.filter(pk=event.pk).exists()


def test_protected_delete_becomes_409_not_500(client_for, platform_admin, make_event, customer):
    # A draft with a booking (only reachable by direct DB edits) still can't be deleted:
    # PROTECT raises ProtectedError, which our exception handler maps to 409.
    event = make_event(status=Event.Status.DRAFT)
    seat = event.seats.first()
    Booking.objects.create(user=customer, seat=seat, amount=seat.price)

    response = client_for(platform_admin).delete(detail_url(event))

    assert response.status_code == 409
    assert Event.objects.filter(pk=event.pk).exists()
