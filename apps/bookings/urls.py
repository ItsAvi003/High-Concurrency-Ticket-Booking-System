from rest_framework.routers import DefaultRouter

from apps.bookings import views

app_name = "bookings"

router = DefaultRouter()
router.register("bookings", views.BookingViewSet, basename="booking")

urlpatterns = router.urls
