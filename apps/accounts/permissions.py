"""
Role-based DRF permission classes.

DRF calls has_permission() for every request to a view, and has_object_permission()
only when a view calls get_object() (detail, update, delete). Both read request.user,
which JWTAuthentication loads from the database on every request, so a role change
takes effect immediately, even for tokens issued before the change.
"""

from rest_framework.permissions import BasePermission

from apps.accounts.models import User


class HasRole(BasePermission):
    """Allow authenticated users whose role is in `allowed_roles`. Subclass, don't use directly."""

    allowed_roles: frozenset[str] = frozenset()

    def has_permission(self, request, view):
        user = request.user
        # AnonymousUser has no `role`, so check authentication first.
        return bool(user and user.is_authenticated and user.role in self.allowed_roles)


class IsOrganizer(HasRole):
    """Organizers manage events. Admins can do everything an organizer can."""

    allowed_roles = frozenset({User.Role.ORGANIZER, User.Role.ADMIN})
    message = "Organizer role required."


class IsAdminRole(HasRole):
    """
    Platform admins only.

    Named IsAdminRole, not IsAdmin, to avoid confusion with DRF's built-in IsAdminUser,
    which checks Django's is_staff flag instead of our role.
    """

    allowed_roles = frozenset({User.Role.ADMIN})
    message = "Admin role required."


class IsOwnerOrAdminRole(BasePermission):
    """
    Object-level: the object's owner or an admin. Used for things like bookings, where a
    user may see their own but not anyone else's.

    `owner_field` names the FK to User on the object. We compare `<field>_id` rather than
    the related object so the check never costs an extra query.
    """

    owner_field = "user"
    message = "You do not have access to this object."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.role == User.Role.ADMIN:
            return True
        return getattr(obj, f"{self.owner_field}_id") == request.user.pk
