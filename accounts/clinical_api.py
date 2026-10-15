from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Encounter, Membership, Organization, Patient, UsageEvent
from .audit import append_audit_event
from .usage import check_encounter_limit, check_patient_limit, record_usage
from .permissions import ActiveOrganizationPermission
from .serializers import EncounterSerializer, PatientSerializer


class ClinicPageNumberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class PatientListCreateView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {"get": "read", "post": "manage_patients"}

    def get(self, request):
        organization = request.organization_membership.organization
        patients = Patient.objects.filter(organization=organization).select_related("primary_doctor")

        search = request.query_params.get("search", "").strip()
        if search:
            for term in search.split():
                patients = patients.filter(
                    Q(first_name__icontains=term)
                    | Q(last_name__icontains=term)
                    | Q(medical_record_number__icontains=term)
                )

        patient_status = request.query_params.get("status")
        if patient_status:
            if patient_status not in Patient.Status.values:
                raise ValidationError({"status": "Choose a valid patient status."})
            patients = patients.filter(status=patient_status)

        paginator = ClinicPageNumberPagination()
        page = paginator.paginate_queryset(patients, request, view=self)
        data = PatientSerializer(page, many=True, context={"organization": organization}).data
        append_audit_event(
            organization_id=organization.pk,
            actor_user_id=request.user.pk,
            action="patient.listed",
            object_type="patient_collection",
            metadata={"returned": len(data)},
        )
        return paginator.get_paginated_response(data)

    def post(self, request):
        organization = request.organization_membership.organization
        serializer = PatientSerializer(
            data=request.data,
            context={"organization": organization},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked_organization = Organization.objects.select_for_update().get(pk=organization.pk)
            check_patient_limit(locked_organization)
            patient = serializer.save(organization=organization)
            record_usage(
                organization_id=organization.pk, actor_user_id=request.user.pk,
                metric=UsageEvent.Metric.PATIENT_CREATED,
            )
            append_audit_event(
                organization_id=organization.pk, actor_user_id=request.user.pk,
                action="patient.created", object_type="patient", object_id=patient.pk,
            )
        return Response(
            PatientSerializer(patient, context={"organization": organization}).data,
            status=status.HTTP_201_CREATED,
        )


class PatientDetailView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {
        "get": "read", "patch": "manage_patients", "put": "manage_patients", "delete": "manage_patients",
    }

    def _get_patient(self, request, patient_id):
        return get_object_or_404(
            Patient.objects.select_related("primary_doctor"),
            id=patient_id,
            organization_id=request.organization_membership.organization_id,
        )

    def get(self, request, patient_id):
        patient = self._get_patient(request, patient_id)
        data = PatientSerializer(patient, context={"organization": patient.organization}).data
        append_audit_event(
            organization_id=patient.organization_id, actor_user_id=request.user.pk,
            action="patient.read", object_type="patient", object_id=patient.pk,
        )
        return Response(data)

    def _update(self, request, patient_id, partial):
        patient = self._get_patient(request, patient_id)
        serializer = PatientSerializer(
            patient,
            data=request.data,
            partial=partial,
            context={"organization": patient.organization},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            patient = serializer.save()
            append_audit_event(
                organization_id=patient.organization_id, actor_user_id=request.user.pk,
                action="patient.updated", object_type="patient", object_id=patient.pk,
            )
        return Response(PatientSerializer(patient, context={"organization": patient.organization}).data)

    def put(self, request, patient_id):
        return self._update(request, patient_id, partial=False)

    def patch(self, request, patient_id):
        return self._update(request, patient_id, partial=True)

    def delete(self, request, patient_id):
        patient = self._get_patient(request, patient_id)
        try:
            with transaction.atomic():
                patient.delete()
                append_audit_event(
                    organization_id=request.organization_membership.organization_id,
                    actor_user_id=request.user.pk,
                    action="patient.deleted", object_type="patient", object_id=patient_id,
                )
        except ProtectedError:
            return Response(
                {"error": {
                    "code": "patient_has_encounters",
                    "message": "Patients with encounters cannot be deleted.",
                }},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class EncounterListCreateView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {"get": "read", "post": "manage_encounters"}

    def get(self, request):
        organization = request.organization_membership.organization
        encounters = Encounter.objects.filter(organization=organization).select_related(
            "patient", "created_by", "assigned_doctor"
        )
        encounter_status = request.query_params.get("status")
        if encounter_status:
            if encounter_status not in Encounter.Status.values:
                raise ValidationError({"status": "Choose a valid encounter status."})
            encounters = encounters.filter(status=encounter_status)
        patient_id = request.query_params.get("patient_id")
        if patient_id:
            patient_id = serializers.IntegerField(min_value=1).run_validation(patient_id)
            encounters = encounters.filter(patient_id=patient_id)

        paginator = ClinicPageNumberPagination()
        page = paginator.paginate_queryset(encounters, request, view=self)
        data = EncounterSerializer(page, many=True, context={"organization": organization}).data
        append_audit_event(
            organization_id=organization.pk, actor_user_id=request.user.pk,
            action="encounter.listed", object_type="encounter_collection",
            metadata={"returned": len(data)},
        )
        return paginator.get_paginated_response(data)

    def post(self, request):
        membership = request.organization_membership
        organization = membership.organization
        serializer = EncounterSerializer(
            data=request.data,
            context={"organization": organization},
        )
        serializer.is_valid(raise_exception=True)
        defaults = {"organization": organization, "created_by": request.user}
        if membership.role == Membership.Role.DOCTOR and "assigned_doctor_id" not in request.data:
            defaults["assigned_doctor"] = request.user
        with transaction.atomic():
            locked_organization = Organization.objects.select_for_update().get(pk=organization.pk)
            check_encounter_limit(locked_organization)
            encounter = serializer.save(**defaults)
            record_usage(
                organization_id=organization.pk, actor_user_id=request.user.pk,
                metric=UsageEvent.Metric.ENCOUNTER_CREATED,
            )
            append_audit_event(
                organization_id=organization.pk, actor_user_id=request.user.pk,
                action="encounter.created", object_type="encounter", object_id=encounter.pk,
            )
        return Response(
            EncounterSerializer(encounter, context={"organization": organization}).data,
            status=status.HTTP_201_CREATED,
        )


class EncounterDetailView(APIView):
    permission_classes = (IsAuthenticated, ActiveOrganizationPermission)
    organization_permissions = {
        "get": "read", "patch": "manage_encounters", "put": "manage_encounters", "delete": "manage_encounters",
    }

    def _get_encounter(self, request, encounter_id):
        return get_object_or_404(
            Encounter.objects.select_related("patient", "created_by", "assigned_doctor"),
            id=encounter_id,
            organization_id=request.organization_membership.organization_id,
        )

    def get(self, request, encounter_id):
        encounter = self._get_encounter(request, encounter_id)
        data = EncounterSerializer(encounter, context={"organization": encounter.organization}).data
        append_audit_event(
            organization_id=encounter.organization_id, actor_user_id=request.user.pk,
            action="encounter.read", object_type="encounter", object_id=encounter.pk,
        )
        return Response(data)

    def _update(self, request, encounter_id, partial):
        encounter = self._get_encounter(request, encounter_id)
        serializer = EncounterSerializer(
            encounter,
            data=request.data,
            partial=partial,
            context={"organization": encounter.organization},
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            encounter = serializer.save()
            append_audit_event(
                organization_id=encounter.organization_id, actor_user_id=request.user.pk,
                action="encounter.updated", object_type="encounter", object_id=encounter.pk,
            )
        return Response(EncounterSerializer(
            encounter, context={"organization": encounter.organization}
        ).data)

    def put(self, request, encounter_id):
        return self._update(request, encounter_id, partial=False)

    def patch(self, request, encounter_id):
        return self._update(request, encounter_id, partial=True)

    def delete(self, request, encounter_id):
        encounter = self._get_encounter(request, encounter_id)
        with transaction.atomic():
            encounter.delete()
            append_audit_event(
                organization_id=encounter.organization_id, actor_user_id=request.user.pk,
                action="encounter.deleted", object_type="encounter", object_id=encounter_id,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
