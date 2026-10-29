from django.contrib import admin

from apps.events.models import Event, Seat, Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "rows", "seats_per_row", "capacity")
    search_fields = ("name", "city")
    list_filter = ("city",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "venue", "organizer", "starts_at", "status", "price")
    list_filter = ("status", "venue__city")
    search_fields = ("title", "organizer__email")
    list_select_related = ("venue", "organizer")  # avoid one query per row in the list page
    raw_id_fields = ("organizer",)  # a text box, not a dropdown of every user
    date_hierarchy = "starts_at"


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ("event", "row_label", "number", "price", "status")
    list_filter = ("status",)
    search_fields = ("event__title",)
    list_select_related = ("event",)
    raw_id_fields = ("event",)
