from django.utils import timezone
from rest_framework import serializers

from apps.events import services
from apps.events.models import Event, Seat, Venue


class VenueSerializer(serializers.ModelSerializer):
    capacity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Venue
        fields = ["id", "name", "city", "address", "rows", "seats_per_row", "capacity"]


class VenueSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Venue
        fields = ["id", "name", "city"]


class SeatSerializer(serializers.ModelSerializer):
    row = serializers.CharField(source="row_label", read_only=True)

    class Meta:
        model = Seat
        fields = ["id", "row", "number", "price", "status"]


# --- Public (read-only) --------------------------------------------------------------
# total_seats / available_seats come from EventQuerySet.with_seat_counts() annotations,
# so every queryset these serializers receive must be annotated.


class PublicEventListSerializer(serializers.ModelSerializer):
    venue = VenueSummarySerializer(read_only=True)
    total_seats = serializers.IntegerField(read_only=True)
    available_seats = serializers.IntegerField(read_only=True)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "starts_at",
            "ends_at",
            "price",
            "venue",
            "total_seats",
            "available_seats",
        ]


class PublicEventDetailSerializer(PublicEventListSerializer):
    venue = VenueSerializer(read_only=True)

    class Meta(PublicEventListSerializer.Meta):
        fields = PublicEventListSerializer.Meta.fields + ["description"]


class EventFilterSerializer(serializers.Serializer):
    """Validates query parameters for the public list, e.g. ?city=Pune&starts_after=..."""

    city = serializers.CharField(required=False)
    starts_after = serializers.DateTimeField(required=False)
    starts_before = serializers.DateTimeField(required=False)


# --- Organizer (read/write) ----------------------------------------------------------


class OrganizerEventSerializer(serializers.ModelSerializer):
    venue = serializers.PrimaryKeyRelatedField(queryset=Venue.objects.all())
    total_seats = serializers.IntegerField(read_only=True)
    available_seats = serializers.IntegerField(read_only=True)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "description",
            "venue",
            "starts_at",
            "ends_at",
            "price",
            "status",
            "total_seats",
            "available_seats",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        event = self.instance  # None on create
        # On PATCH only the sent fields are in attrs; fall back to current values.
        starts_at = attrs.get("starts_at", event.starts_at if event else None)
        ends_at = attrs.get("ends_at", event.ends_at if event else None)
        new_status = attrs.get("status", event.status if event else Event.Status.DRAFT)

        if event is None:
            if new_status != Event.Status.DRAFT:
                raise serializers.ValidationError({"status": "Events are created as drafts."})
            if starts_at <= timezone.now():
                raise serializers.ValidationError({"starts_at": "Must be in the future."})
        else:
            if event.status == Event.Status.CANCELLED:
                raise serializers.ValidationError("Cancelled events cannot be edited.")
            if "venue" in attrs and attrs["venue"] != event.venue:
                # Seats were generated from the original venue's layout.
                raise serializers.ValidationError(
                    {"venue": "The venue cannot be changed after the event is created."}
                )
            if not event.can_transition_to(new_status):
                raise serializers.ValidationError(
                    {"status": f"Cannot change status from {event.status} to {new_status}."}
                )
            if new_status == Event.Status.PUBLISHED and starts_at <= timezone.now():
                raise serializers.ValidationError(
                    {"status": "Cannot publish an event that has already started."}
                )

        # Mirrors the event_ends_after_start DB constraint, but returns a readable 400.
        if ends_at <= starts_at:
            raise serializers.ValidationError({"ends_at": "Must be after starts_at."})
        return attrs

    def create(self, validated_data):
        # `organizer` arrives via serializer.save(organizer=request.user) in the view.
        return services.create_event_with_seats(**validated_data)

    def update(self, instance, validated_data):
        return services.update_event(instance, **validated_data)
