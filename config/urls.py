"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""

from django.contrib import admin
from django.urls import path
from accounts.views import index, login_view
from accounts.api_views import (
    CurrentUserView,
    LoginView,
    LogoutView,
    RegisterView,
    csrf_cookie,
)
from accounts.organization_api import (
    InvitationAcceptView,
    OrganizationDetailView,
    OrganizationInvitationCreateView,
    OrganizationListCreateView,
    OrganizationMemberDetailView,
    OrganizationMembersView,
    OrganizationSelectionView,
    ProfileView,
)
from accounts.clinical_api import (
    EncounterDetailView,
    EncounterListCreateView,
    PatientDetailView,
    PatientListCreateView,
)
from accounts.audit_api import AuditVerificationView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", index, name="index"),
    path("login/", login_view, name="login"),
    path("api/auth/csrf/", csrf_cookie, name="auth-csrf"),
    path("api/auth/register/", RegisterView.as_view(), name="auth-register"),
    path("api/auth/login/", LoginView.as_view(), name="auth-login"),
    path("api/auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("api/auth/me/", CurrentUserView.as_view(), name="auth-me"),
    # Versioned API paths are canonical for new clients. The unversioned paths
    # above remain available so the existing browser frontend keeps working.
    path("api/v1/auth/csrf/", csrf_cookie, name="v1-auth-csrf"),
    path("api/v1/auth/register/", RegisterView.as_view(), name="v1-auth-register"),
    path("api/v1/auth/login/", LoginView.as_view(), name="v1-auth-login"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="v1-auth-logout"),
    path("api/v1/auth/me/", CurrentUserView.as_view(), name="v1-auth-me"),
    path("api/v1/profile/", ProfileView.as_view(), name="v1-profile"),
    path("api/v1/organizations/", OrganizationListCreateView.as_view(), name="v1-organizations"),
    path("api/v1/organizations/selection/", OrganizationSelectionView.as_view(), name="v1-organization-selection"),
    path("api/v1/organizations/<int:organization_id>/", OrganizationDetailView.as_view(), name="v1-organization-detail"),
    path("api/v1/organizations/<int:organization_id>/members/", OrganizationMembersView.as_view(), name="v1-organization-members"),
    path("api/v1/organizations/<int:organization_id>/members/<int:user_id>/", OrganizationMemberDetailView.as_view(), name="v1-organization-member-detail"),
    path("api/v1/organizations/<int:organization_id>/invitations/", OrganizationInvitationCreateView.as_view(), name="v1-organization-invitation"),
    path("api/v1/invitations/accept/", InvitationAcceptView.as_view(), name="v1-invitation-accept"),
    path("api/v1/patients/", PatientListCreateView.as_view(), name="v1-patients"),
    path("api/v1/patients/<int:patient_id>/", PatientDetailView.as_view(), name="v1-patient-detail"),
    path("api/v1/encounters/", EncounterListCreateView.as_view(), name="v1-encounters"),
    path("api/v1/encounters/<int:encounter_id>/", EncounterDetailView.as_view(), name="v1-encounter-detail"),
    path("api/v1/audit/verify/", AuditVerificationView.as_view(), name="v1-audit-verify"),
]
