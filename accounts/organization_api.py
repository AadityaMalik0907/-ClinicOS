import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Membership, Organization, OrganizationInvitation, UserProfile
from .serializers import (
    MembershipSerializer,
    OrganizationInvitationSerializer,
    OrganizationSerializer,
    PublicUserSerializer,
    UserProfileSerializer,
)
from .permissions import (
    OrganizationRolePermission,
    membership_for,
    organization_queryset,
    require_organization_permission,
)


class InvitationServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Invitation email delivery is not configured for this deployment."
    default_code = "service_unavailable"


class OrganizationListCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        organizations = organization_queryset(request.user, Organization.objects.all())
        return Response(OrganizationSerializer(organizations, many=True, context={"request": request}).data)

    def post(self, request):
        serializer = OrganizationSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                organization = serializer.save()
                Membership.objects.create(
                    user=request.user,
                    organization=organization,
                    role=Membership.Role.OWNER,
                )
        except IntegrityError:
            raise serializers.ValidationError({"slug": "An organization with this slug already exists."})
        return Response(
            OrganizationSerializer(organization, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class OrganizationDetailView(APIView):
    permission_classes = (IsAuthenticated, OrganizationRolePermission)
    organization_permissions = {
        "get": "read",
        "patch": "manage_organization",
        "delete": "delete_organization",
    }

    def get(self, request, organization_id):
        membership = membership_for(request.user, organization_id)
        return Response(OrganizationSerializer(membership.organization, context={"request": request}).data)

    def patch(self, request, organization_id):
        membership = membership_for(request.user, organization_id)
        require_organization_permission(membership, "manage_organization")
        serializer = OrganizationSerializer(
            membership.organization,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            organization = serializer.save()
        except IntegrityError:
            raise serializers.ValidationError({"slug": "An organization with this slug already exists."})
        return Response(OrganizationSerializer(organization, context={"request": request}).data)

    def delete(self, request, organization_id):
        membership = request.organization_membership
        if membership.organization.patients.exists() or membership.organization.encounters.exists():
            raise serializers.ValidationError(
                {"organization": "Organizations with patient or encounter records cannot be deleted."}
            )
        membership.organization.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationSelectionView(APIView):
    """Store the active organization in this browser session, not on the user."""

    permission_classes = (IsAuthenticated,)
    session_key = "active_organization_id"

    def get(self, request):
        organization_id = request.session.get(self.session_key)
        if organization_id is None:
            return Response({"organization": None})
        membership = membership_for(request.user, organization_id)
        return Response(MembershipSerializer(membership).data)

    def put(self, request):
        organization_id = request.data.get("organization_id")
        if organization_id is None:
            raise serializers.ValidationError({"organization_id": "This field is required."})
        organization_id = serializers.IntegerField().run_validation(organization_id)
        membership = membership_for(request.user, organization_id)
        request.session[self.session_key] = membership.organization_id
        return Response(MembershipSerializer(membership).data)

    def delete(self, request):
        request.session.pop(self.session_key, None)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationMembersView(APIView):
    permission_classes = (IsAuthenticated, OrganizationRolePermission)
    organization_permissions = {"get": "read"}

    def get(self, request, organization_id):
        membership_for(request.user, organization_id)
        members = Membership.objects.filter(organization_id=organization_id).select_related("user")
        return Response(MembershipSerializer(members, many=True).data)


class OrganizationMemberDetailView(APIView):
    permission_classes = (IsAuthenticated, OrganizationRolePermission)
    organization_permissions = {"patch": "manage_members", "delete": "manage_members"}

    def _get_manageable_membership(self, request, organization_id, user_id):
        manager = membership_for(request.user, organization_id)
        require_organization_permission(manager, "manage_members")
        target = get_object_or_404(
            Membership.objects.select_related("user", "organization"),
            organization_id=organization_id,
            user_id=user_id,
        )
        if target.role == Membership.Role.OWNER:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("The organization owner cannot be changed here.")
        return target

    def patch(self, request, organization_id, user_id):
        target = self._get_manageable_membership(request, organization_id, user_id)
        role = request.data.get("role")
        if role not in Membership.Role.values or role == Membership.Role.OWNER:
            raise serializers.ValidationError({"role": "Choose a non-owner organization role."})
        target.role = role
        target.save(update_fields=("role",))
        return Response(MembershipSerializer(target).data)

    def delete(self, request, organization_id, user_id):
        target = self._get_manageable_membership(request, organization_id, user_id)
        target.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationInvitationCreateView(APIView):
    permission_classes = (IsAuthenticated, OrganizationRolePermission)
    organization_permissions = {"post": "manage_members"}

    def post(self, request, organization_id):
        membership = membership_for(request.user, organization_id)
        require_organization_permission(membership, "manage_members")

        email = serializers.EmailField().run_validation(str(request.data.get("email", "")).strip()).lower()
        role = request.data.get("role", Membership.Role.STAFF)
        if role not in Membership.Role.values:
            raise serializers.ValidationError({"role": "Choose a valid organization role."})
        if role == Membership.Role.OWNER:
            raise serializers.ValidationError({"role": "Owner membership cannot be assigned by invitation."})
        if Membership.objects.filter(organization_id=organization_id, user__email__iexact=email).exists():
            raise serializers.ValidationError({"email": "This user is already a member of the organization."})
        if OrganizationInvitation.objects.filter(
            organization_id=organization_id,
            email__iexact=email,
            accepted_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).exists():
            raise serializers.ValidationError({"email": "An active invitation already exists for this address."})

        if not settings.EXPOSE_INVITATION_TOKENS and (
            not settings.EMAIL_HOST or "localhost" in settings.DEFAULT_FROM_EMAIL.lower()
        ):
            raise InvitationServiceUnavailable("Invitation email delivery is not configured for this deployment.")

        raw_token = secrets.token_urlsafe(32)
        with transaction.atomic():
            invitation = OrganizationInvitation.objects.create(
                organization_id=organization_id,
                invited_by=request.user,
                email=email,
                role=role,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=timezone.now() + timedelta(days=7),
            )
            if not settings.EXPOSE_INVITATION_TOKENS:
                site_url = settings.SITE_URL or request.build_absolute_uri("/").rstrip("/")
                invite_url = f"{site_url}/login/?accept_invite=1#invite={raw_token}"
                sent = send_mail(
                    subject=f"Invitation to join {membership.organization.name} on ClinicOS",
                    message=(
                        f"You have been invited to join {membership.organization.name} as {role}.\n\n"
                        f"Sign in or create an account with this email address, then accept the invitation:\n"
                        f"{invite_url}\n\nThis link expires in 7 days. If you were not expecting this invitation, ignore this email."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
                if sent != 1:
                    raise InvitationServiceUnavailable("Invitation email could not be delivered.")
        response = OrganizationInvitationSerializer(invitation).data
        # The raw token is returned only for local development, never in production responses.
        if settings.EXPOSE_INVITATION_TOKENS:
            response["token"] = raw_token
        return Response(response, status=status.HTTP_201_CREATED)


class InvitationAcceptView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        raw_token = str(request.data.get("token", ""))
        if not raw_token:
            raise serializers.ValidationError({"token": "This field is required."})
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with transaction.atomic():
            invitation = get_object_or_404(
                OrganizationInvitation.objects.select_for_update().select_related("organization"),
                token_hash=token_hash,
            )
            if not invitation.is_active:
                raise serializers.ValidationError({"token": "This invitation is expired or already accepted."})
            if invitation.email.lower() != request.user.email.lower():
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("This invitation was issued for a different email address.")
            membership, _ = Membership.objects.get_or_create(
                user=request.user,
                organization=invitation.organization,
                defaults={"role": invitation.role},
            )
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=("accepted_at",))
        return Response(MembershipSerializer(membership).data, status=status.HTTP_200_OK)


class ProfileView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        return Response(UserProfileSerializer(profile).data)

    def patch(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
