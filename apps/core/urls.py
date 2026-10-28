from django.urls import path

from apps.core import views

app_name = "core"

urlpatterns = [
    path("live/", views.liveness, name="health-live"),
    path("ready/", views.readiness, name="health-ready"),
]
