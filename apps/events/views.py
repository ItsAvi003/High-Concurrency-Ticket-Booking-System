from django.shortcuts import get_object_or_404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminRole, IsOrganizer
from apps.core.exceptions import Conflict
from apps.events.models import Event, Seat, Venue
from apps.events.serializers import (
    EventFilterSerializer,
    OrganizerEventSerializer,
    PublicEventDetailSerializer,
    PublicEventListSerializer,
    SeatSerializer,
    VenueSerializer,
)


class SeatPagination(PageNumberPagination):
    """A seat map needs much larger pages than an event list."""

    page_size = 200
    page_size_query_param = "page_size"
    max_page_size = 1000


class VenueViewSet(viewsets.ModelViewSet):
    """Anyone can read venues; only platform admins can create, edit or delete them."""

    queryset = Venue.objects.order_by("city", "name")
    serializer_class = VenueSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [AllowAny()]
        return [IsAdminRole()]


class PublicEventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /events/            published, upcoming events (filters: city, starts_after, starts_before)
    GET /events/<id>/       one of them
    GET /events/<id>/seats/ its seat map (filter: status)
    """

    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = (
            Event.objects.publicly_visible()
            .with_seat_counts()
            .select_related("venue")  # JOIN venue now, instead of one query per event later
            .order_by("starts_at", "id")  # id breaks ties so pagination order is stable
        )
        if self.action == "list":
            queryset = self._apply_filters(queryset)
        return queryset

    def _apply_filters(self, queryset):
        params = EventFilterSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)  # bad dates -> 400, not a 500 or silent ignore
        filters = params.validated_data
        if "city" in filters:
            queryset = queryset.filter(venue__city__iexact=filters["city"])
        if "starts_after" in filters:
            queryset = queryset.filter(starts_at__gte=filters["starts_after"])
        if "starts_before" in filters:
            queryset = queryset.filter(starts_at__lt=filters["starts_before"])
        return queryset

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PublicEventDetailSerializer
        return PublicEventListSerializer

    @action(detail=True, methods=["get"])
    def seats(self, request, pk=None):
        # Plain visibility check: the seat-count annotation isn't needed here.
        event = get_object_or_404(Event.objects.publicly_visible(), pk=pk)
        seats = event.seats.order_by("row_number", "number")
        seat_status = request.query_params.get("status")
        if seat_status in Seat.Status.values:
            seats = seats.filter(status=seat_status)

        paginator = SeatPagination()
        page = paginator.paginate_queryset(seats, request, view=self)
        return paginator.get_paginated_response(SeatSerializer(page, many=True).data)


class OrganizerEventViewSet(viewsets.ModelViewSet):
    """
    /organizer/events/ - full CRUD for the organizer's own events (admins see all).

    Ownership is enforced by scoping the queryset: another organizer's event is simply
    not found (404), so the API never confirms that someone else's event id exists.
    """

    serializer_class = OrganizerEventSerializer
    permission_classes = [IsOrganizer]

    def get_queryset(self):
        queryset = Event.objects.with_seat_counts().order_by("-created_at", "-id")
        if self.request.user.role != User.Role.ADMIN:
            queryset = queryset.filter(organizer=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(organizer=self.request.user)
        self._reload_with_counts(serializer)

    def perform_update(self, serializer):
        serializer.save()
        self._reload_with_counts(serializer)

    def _reload_with_counts(self, serializer):
        # The saved instance has no seat-count annotations; re-read it so the response does.
        serializer.instance = self.get_queryset().get(pk=serializer.instance.pk)

    def perform_destroy(self, instance):
        if instance.status != Event.Status.DRAFT:
            raise Conflict("Only draft events can be deleted. Cancel a published event instead.")
        instance.delete()
