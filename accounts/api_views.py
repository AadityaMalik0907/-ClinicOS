from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Membership, UserProfile
from .serializers import (
    LoginSerializer,
    MembershipSerializer,
    PublicUserSerializer,
    RegistrationSerializer,
    UserProfileSerializer,
)


@ensure_csrf_cookie
def csrf_cookie(request):
    """Set the CSRF cookie that browser clients send with unsafe requests."""
    return JsonResponse({"detail": "CSRF cookie set"})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                user = serializer.save()
        except IntegrityError:
            # Covers two simultaneous registration requests for the same email.
            return Response(
                {"email": ["An account with this email already exists."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(PublicUserSerializer(user).data, status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["email"].strip().lower(),
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {
                    "error": {
                        "code": "validation_error",
                        "message": "Invalid email or password.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request, user)
        return Response({"user": PublicUserSerializer(user).data})


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        memberships = Membership.objects.filter(user=request.user).select_related("organization")
        data = PublicUserSerializer(request.user).data
        data["profile"] = UserProfileSerializer(profile).data
        data["memberships"] = MembershipSerializer(memberships, many=True).data
        active_organization_id = request.session.get("active_organization_id")
        active_membership = memberships.filter(organization_id=active_organization_id).first()
        data["active_organization"] = (
            MembershipSerializer(active_membership).data if active_membership else None
        )
        return Response(data)
