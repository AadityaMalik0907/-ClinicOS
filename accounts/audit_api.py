from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import ActiveOrganizationPermission
from .models import AuditEvent
from .audit import verify_audit_chain


class AuditVerificationView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {"get": "view_audit"}

    def get(self, request):
        result = verify_audit_chain(request.organization_membership.organization_id)
        return Response(result, status=200 if result["valid"] else 409)


class AuditEventListView(APIView):
    """List recent, non-clinical audit metadata for the selected organization."""

    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {"get": "view_audit"}

    def get(self, request):
        organization_id = request.organization_membership.organization_id
        events = AuditEvent.objects.filter(organization_id=organization_id).order_by("-sequence")[:100]
        return Response({"results": [
            {
                "sequence": event.sequence,
                "actor_user_id": event.actor_user_id,
                "action": event.action,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "created_at": event.created_at,
                "previous_hash": event.previous_hash,
                "entry_hash": event.entry_hash,
            }
            for event in events
        ]})
