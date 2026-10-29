from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Event, Seat

pytestmark = pytest.mark.django_db

LIST_URL = reverse("events:event-list")


def detail_url(event):
    return reverse("events:event-detail", kwargs={"pk": event.pk})


def seats_url(event):
    return reverse("events:event-seats", kwargs={"pk": event.pk})


def _ids(response):
    return [item["id"] for item in response.json()["results"]]


def test_anonymous_can_list_published_upcoming_events(api_client, make_event):
    event = make_event()

    response = api_client.get(LIST_URL)

    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["id"] == event.pk
    assert item["venue"] == {"id": event.venue_id, "name": event.venue.name, "city": "Pune"}
    assert item["total_seats"] == 12
    assert item["available_seats"] == 12
    assert item["price"] == "499.00"  # Decimal serialized as a string: exact, no float rounding


def test_list_hides_drafts_cancelled_and_past_events(api_client, make_event):
    visible = make_event()
    make_event(status=Event.Status.DRAFT)
    make_event(status=Event.Status.CANCELLED)
    make_event(starts_in=-timedelta(days=1))  # published, but already started

    assert _ids(api_client.get(LIST_URL)) == [visible.pk]


def test_list_is_ordered_by_start_time(api_client, make_event):
    later = make_event(starts_in=timedelta(days=10))
    sooner = make_event(starts_in=timedelta(days=2))

    assert _ids(api_client.get(LIST_URL)) == [sooner.pk, later.pk]


def test_available_seats_reflects_booked_seats(api_client, make_event):
    event = make_event()
    Seat.objects.filter(pk__in=event.seats.values("pk")[:5]).update(status=Seat.Status.BOOKED)

    item = api_client.get(LIST_URL).json()["results"][0]

    assert (item["total_seats"], item["available_seats"]) == (12, 7)


def test_filter_by_city_is_case_insensitive(api_client, make_event, make_venue):
    pune = make_event(venue=make_venue(city="Pune"))
    make_event(venue=make_venue(city="Mumbai"))

    assert _ids(api_client.get(LIST_URL, {"city": "pune"})) == [pune.pk]


def test_filter_by_start_window(api_client, make_event):
    make_event(starts_in=timedelta(days=1))
    in_window = make_event(starts_in=timedelta(days=5))
    make_event(starts_in=timedelta(days=20))
    now = timezone.now()

    response = api_client.get(
        LIST_URL,
        {
            "starts_after": (now + timedelta(days=3)).isoformat(),
            "starts_before": (now + timedelta(days=10)).isoformat(),
        },
    )

    assert _ids(response) == [in_window.pk]


def test_invalid_filter_value_is_400(api_client):
    response = api_client.get(LIST_URL, {"starts_after": "next tuesday"})

    assert response.status_code == 400
    assert "starts_after" in response.json()


def test_list_query_count_does_not_grow_with_number_of_events(
    api_client, make_event, django_assert_num_queries
):
    # Guards against N+1: venue is JOINed and seat counts are aggregated in SQL.
    for _ in range(8):
        make_event()

    # Exactly 2, whether there is 1 event or 8: COUNT(*) for the paginator + the page query.
    # Without select_related/annotate this would be 2 + 3 queries per event.
    with django_assert_num_queries(2):
        response = api_client.get(LIST_URL)

    assert len(response.json()["results"]) == 8


def test_detail_includes_full_venue_and_description(api_client, make_event):
    event = make_event(description="Live in concert")

    body = api_client.get(detail_url(event)).json()

    assert body["description"] == "Live in concert"
    assert body["venue"]["capacity"] == 12
    assert body["available_seats"] == 12


@pytest.mark.parametrize("status", [Event.Status.DRAFT, Event.Status.CANCELLED])
def test_detail_of_non_public_event_is_404(api_client, make_event, status):
    assert api_client.get(detail_url(make_event(status=status))).status_code == 404


def test_public_endpoints_are_read_only(client_for, organizer, make_event):
    event = make_event(organizer=organizer)
    client = client_for(organizer)  # even the owner can't write through the public API

    assert client.post(LIST_URL, {"title": "x"}).status_code == 405
    assert client.patch(detail_url(event), {"title": "x"}).status_code == 405
    assert client.delete(detail_url(event)).status_code == 405


def test_seat_map_is_ordered_and_labelled(api_client, make_event, make_venue):
    event = make_event(venue=make_venue(rows=2, seats_per_row=2))

    body = api_client.get(seats_url(event)).json()

    assert body["count"] == 4
    assert [(s["row"], s["number"]) for s in body["results"]] == [
        ("A", 1), ("A", 2), ("B", 1), ("B", 2),
    ]  # fmt: skip


def test_seat_map_status_filter(api_client, make_event):
    event = make_event()
    booked = event.seats.first()
    booked.status = Seat.Status.BOOKED
    booked.save()

    body = api_client.get(seats_url(event), {"status": "available"}).json()

    assert body["count"] == 11
    assert booked.pk not in [s["id"] for s in body["results"]]


def test_seat_map_of_draft_event_is_404(api_client, make_event):
    assert api_client.get(seats_url(make_event(status=Event.Status.DRAFT))).status_code == 404
