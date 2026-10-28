from rest_framework import generics
from rest_framework.permissions import AllowAny

from apps.accounts.models import User
from apps.accounts.permissions import IsAdminRole
from apps.accounts.serializers import RegisterSerializer, RoleUpdateSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    """POST /api/v1/auth/register/ - create an account with role=user."""

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    # Skip authentication entirely, so a stale or garbage Authorization header sent by
    # a client can't turn a signup into a 401.
    authentication_classes = []


class MeView(generics.RetrieveAPIView):
    """GET /api/v1/auth/me/ - the logged-in user's own profile, including role."""

    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class UserListView(generics.ListAPIView):
    """GET /api/v1/users/ - admin only."""

    queryset = User.objects.order_by("id")  # stable order is required for pagination
    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]


class UserRoleUpdateView(generics.UpdateAPIView):
    """PATCH /api/v1/users/<id>/role/ - admin promotes or demotes a user."""

    queryset = User.objects.all()
    serializer_class = RoleUpdateSerializer
    permission_classes = [IsAdminRole]
    http_method_names = ["patch", "options"]
