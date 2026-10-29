from django.contrib import admin

from apps.bookings.models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "seat", "status", "amount", "created_at")
    list_filter = ("status",)
    search_fields = ("user__email", "seat__event__title")
    list_select_related = ("user", "seat__event")
    raw_id_fields = ("user", "seat")
