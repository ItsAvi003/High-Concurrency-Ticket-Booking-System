from rest_framework.routers import DefaultRouter

from apps.events import views

app_name = "events"

# The router generates list/detail URLs for each viewset, e.g.
#   events/            -> event-list      events/<pk>/        -> event-detail
#   events/<pk>/seats/ -> event-seats     organizer/events/<pk>/ -> organizer-event-detail
router = DefaultRouter()
router.register("venues", views.VenueViewSet, basename="venue")
router.register("events", views.PublicEventViewSet, basename="event")
router.register("organizer/events", views.OrganizerEventViewSet, basename="organizer-event")

urlpatterns = router.urls
