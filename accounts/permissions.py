from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission

from .models import Membership


# Keep organization capabilities in one place so every API view applies the
# same role rules. Read access is available to all active organization members.
ROLE_PERMISSIONS = {
    Membership.Role.OWNER: {
        "read", "manage_organization", "manage_members", "delete_organization",
        "manage_patients", "manage_encounters", "edit_clinical_notes",
        "manage_appointments", "view_audit", "view_usage",
    },
    Membership.Role.ADMIN: {
        "read", "manage_organization", "manage_members", "manage_patients",
        "manage_encounters", "edit_clinical_notes", "manage_appointments", "view_audit", "view_usage",
    },
    Membership.Role.DOCTOR: {"read", "manage_patients", "manage_encounters", "edit_clinical_notes"},
    Membership.Role.STAFF: {"read", "manage_appointments"},
    Membership.Role.VIEWER: {"read"},
}


def membership_for(user, organization_id):
    try:
        return Membership.objects.select_related("organization", "user").get(
            user=user, organization_id=organization_id
        )
    except Membership.DoesNotExist:
        # Do not reveal whether an inaccessible organization exists.
        from django.http import Http404

        raise Http404


def has_organization_permission(membership, permission):
    return permission in ROLE_PERMISSIONS.get(membership.role, set())


def require_organization_permission(membership, permission):
    if not has_organization_permission(membership, permission):
        raise PermissionDenied("Your organization role does not allow this action.")
    return membership


def organization_queryset(user, queryset, organization_field=None):
    """Restrict an organization-owned queryset to the user's memberships."""
    membership_path = "memberships__user" if organization_field is None else f"{organization_field}__memberships__user"
    return queryset.filter(**{membership_path: user}).distinct()


def active_membership_for(request):
    organization_id = request.session.get("active_organization_id")
    if organization_id is None:
        raise ValidationError({"organization": "Select an active organization first."})
    return membership_for(request.user, organization_id)


class OrganizationRolePermission(BasePermission):
    """DRF permission that resolves organization membership before a view runs."""

    def has_permission(self, request, view):
        organization_id = view.kwargs.get("organization_id")
        if organization_id is None:
            return True
        membership = membership_for(request.user, organization_id)
        permission = self._permission_for(request, view)
        if permission is None:
            return False
        if not has_organization_permission(membership, permission):
            return False
        request.organization_membership = membership
        return True

    @staticmethod
    def _permission_for(request, view):
        method = request.method.lower()
        configured = getattr(view, "organization_permissions", {})
        if method in configured:
            return configured[method]
        return "read" if method in {"get", "head", "options"} else None


class ActiveOrganizationPermission(BasePermission):
    """Require a selected organization and the requested role capability."""

    def has_permission(self, request, view):
        membership = active_membership_for(request)
        permission = OrganizationRolePermission._permission_for(request, view)
        if permission is None:
            return False
        if not has_organization_permission(membership, permission):
            return False
        request.organization_membership = membership
        return True
