from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import ActiveOrganizationPermission
from .usage import usage_summary


class UsageSummaryView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {"get": "view_usage"}

    def get(self, request):
        return Response(usage_summary(request.organization_membership.organization))
