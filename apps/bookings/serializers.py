from rest_framework import serializers

from apps.bookings.models import Booking
from apps.events.models import Event, Seat


class BookingCreateSerializer(serializers.Serializer):
    # A plain integer, not PrimaryKeyRelatedField: that would SELECT the seat *without*
    # a lock during validation, and the service would read it again under the lock anyway.
    seat = serializers.IntegerField(min_value=1)


class BookedSeatSerializer(serializers.ModelSerializer):
    row = serializers.CharField(source="row_label", read_only=True)

    class Meta:
        model = Seat
        fields = ["id", "row", "number"]


class BookedEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "title", "starts_at"]


class BookingSerializer(serializers.ModelSerializer):
    seat = BookedSeatSerializer(read_only=True)
    event = BookedEventSerializer(source="seat.event", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "status", "amount", "seat", "event", "created_at", "updated_at"]
        read_only_fields = fields
