from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import ActiveOrganizationPermission
from .audit import verify_audit_chain


class AuditVerificationView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {"get": "view_audit"}

    def get(self, request):
        result = verify_audit_chain(request.organization_membership.organization_id)
        return Response(result, status=200 if result["valid"] else 409)
