from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsOwnerOrAdminRole
from apps.bookings import services
from apps.bookings.models import Booking
from apps.bookings.serializers import BookingCreateSerializer, BookingSerializer


class BookingViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    POST /bookings/              {"seat": <id>} -> 201 booking | 409 seat taken | 400 not bookable
    GET  /bookings/              your bookings (admins: everyone's)
    GET  /bookings/<id>/
    POST /bookings/<id>/cancel/  free the seat (pending bookings only, for now)

    No update/delete endpoints: a booking changes only through these actions.
    """

    serializer_class = BookingSerializer
    # Two layers: the queryset hides other users' bookings (404), and the object-level
    # permission would still refuse them if the queryset scoping were ever loosened.
    permission_classes = [IsOwnerOrAdminRole]

    def get_queryset(self):
        queryset = Booking.objects.select_related("seat__event").order_by("-created_at", "-id")
        if self.request.user.role != User.Role.ADMIN:
            queryset = queryset.filter(user=self.request.user)
        return queryset

    def create(self, request, *args, **kwargs):
        payload = BookingCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        booking = services.book_seat(user=request.user, seat_id=payload.validated_data["seat"])
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = services.cancel_booking(booking=self.get_object())
        return Response(BookingSerializer(booking).data)
