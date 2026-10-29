import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

LIST_URL = reverse("events:venue-list")

NEW_VENUE = {"name": "Arena", "city": "Pune", "address": "FC Road", "rows": 10, "seats_per_row": 20}


def detail_url(venue):
    return reverse("events:venue-detail", kwargs={"pk": venue.pk})


def test_anyone_can_list_venues(api_client, make_venue):
    make_venue(rows=2, seats_per_row=5)

    results = api_client.get(LIST_URL).json()["results"]

    assert results[0]["capacity"] == 10


@pytest.mark.parametrize("role_fixture", ["customer", "organizer"])
def test_non_admins_cannot_create_venues(client_for, request, role_fixture):
    user = request.getfixturevalue(role_fixture)

    assert client_for(user).post(LIST_URL, NEW_VENUE).status_code == 403


def test_anonymous_cannot_create_venues(api_client):
    assert api_client.post(LIST_URL, NEW_VENUE).status_code == 401


def test_admin_creates_venue(client_for, platform_admin):
    response = client_for(platform_admin).post(LIST_URL, NEW_VENUE)

    assert response.status_code == 201
    assert response.json()["capacity"] == 200


def test_duplicate_venue_name_in_same_city_is_400(client_for, platform_admin, make_venue):
    make_venue(name="Arena", city="Pune")

    response = client_for(platform_admin).post(LIST_URL, NEW_VENUE)

    assert response.status_code == 400


@pytest.mark.parametrize(("field", "value"), [("rows", 0), ("rows", 101), ("seats_per_row", 201)])
def test_layout_limits_are_400(client_for, platform_admin, field, value):
    response = client_for(platform_admin).post(LIST_URL, {**NEW_VENUE, field: value})

    assert response.status_code == 400
    assert field in response.json()


def test_deleting_venue_used_by_event_is_409(client_for, platform_admin, make_event):
    event = make_event()

    response = client_for(platform_admin).delete(detail_url(event.venue))

    assert response.status_code == 409
