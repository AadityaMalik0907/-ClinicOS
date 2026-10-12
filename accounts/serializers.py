from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Encounter, Membership, Organization, OrganizationInvitation, Patient, UserProfile


User = get_user_model()


class PublicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name")
        read_only_fields = fields


class RegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ("email", "password", "first_name", "last_name")

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        UserProfile.objects.create(user=user)
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ("phone_number", "department", "specialization", "license_number")


class MembershipSerializer(serializers.ModelSerializer):
    organization_id = serializers.IntegerField(source="organization.id", read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    user = PublicUserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ("user", "organization_id", "organization_name", "role", "created_at")
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ("id", "name", "slug", "plan", "created_at", "role")
        read_only_fields = ("id", "plan", "created_at", "role")

    def get_role(self, organization):
        membership = organization.memberships.filter(user=self.context["request"].user).first()
        return membership.role if membership else None


class OrganizationInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationInvitation
        fields = ("id", "email", "role", "expires_at", "created_at")
        read_only_fields = fields


class PatientSummarySerializer(serializers.ModelSerializer):
    mrn = serializers.CharField(source="medical_record_number", read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = ("id", "mrn", "first_name", "last_name", "full_name")
        read_only_fields = fields

    def get_full_name(self, patient):
        return f"{patient.first_name} {patient.last_name}".strip()


class PatientSerializer(serializers.ModelSerializer):
    mrn = serializers.CharField(source="medical_record_number", read_only=True)
    primary_doctor = PublicUserSerializer(read_only=True)
    primary_doctor_name = serializers.SerializerMethodField()
    primary_doctor_id = serializers.PrimaryKeyRelatedField(
        source="primary_doctor", queryset=User.objects.none(), write_only=True,
        allow_null=True, required=False,
    )

    class Meta:
        model = Patient
        fields = (
            "id", "mrn", "first_name", "last_name", "date_of_birth", "gender", "phone",
            "primary_doctor", "primary_doctor_name", "primary_doctor_id", "status",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "mrn", "primary_doctor", "primary_doctor_name", "created_at", "updated_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.context.get("organization")
        if organization:
            doctor_ids = Membership.objects.filter(
                organization=organization, role=Membership.Role.DOCTOR
            ).values_list("user_id", flat=True)
            self.fields["primary_doctor_id"].queryset = User.objects.filter(id__in=doctor_ids)

    def get_primary_doctor_name(self, patient):
        if not patient.primary_doctor_id:
            return ""
        name = f"{patient.primary_doctor.first_name} {patient.primary_doctor.last_name}".strip()
        return name or patient.primary_doctor.email


class EncounterSerializer(serializers.ModelSerializer):
    patient = PatientSummarySerializer(read_only=True)
    patient_id = serializers.PrimaryKeyRelatedField(
        source="patient", queryset=Patient.objects.none(), write_only=True,
    )
    created_by = PublicUserSerializer(read_only=True)
    assigned_doctor = PublicUserSerializer(read_only=True)
    assigned_doctor_name = serializers.SerializerMethodField()
    assigned_doctor_id = serializers.PrimaryKeyRelatedField(
        source="assigned_doctor", queryset=User.objects.none(), write_only=True,
        allow_null=True, required=False,
    )

    class Meta:
        model = Encounter
        fields = (
            "id", "patient", "patient_id", "created_by", "assigned_doctor", "assigned_doctor_name",
            "assigned_doctor_id", "occurred_at", "status", "chief_complaint", "blood_pressure",
            "heart_rate", "temperature", "oxygen_saturation", "objective_notes", "assessment",
            "plan", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "patient", "created_by", "assigned_doctor", "assigned_doctor_name",
            "created_at", "updated_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.context.get("organization")
        if organization:
            self.fields["patient_id"].queryset = Patient.objects.filter(organization=organization)
            doctor_ids = Membership.objects.filter(
                organization=organization, role=Membership.Role.DOCTOR
            ).values_list("user_id", flat=True)
            self.fields["assigned_doctor_id"].queryset = User.objects.filter(id__in=doctor_ids)

    def get_assigned_doctor_name(self, encounter):
        doctor = encounter.assigned_doctor
        if doctor is None:
            return ""
        name = f"{doctor.first_name} {doctor.last_name}".strip()
        return name or doctor.email
