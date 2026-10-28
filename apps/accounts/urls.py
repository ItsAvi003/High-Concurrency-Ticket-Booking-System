from django.urls import path
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    # Login: email + password -> {"access": ..., "refresh": ...}
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    # refresh -> new access (+ new refresh, old one blacklisted)
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    # Logout: blacklist the refresh token so it can't mint new access tokens.
    path("auth/logout/", TokenBlacklistView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<int:pk>/role/", views.UserRoleUpdateView.as_view(), name="user-role"),
]
