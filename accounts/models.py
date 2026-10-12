from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
import uuid
import hashlib
import json

from .fields import EncryptedCharField, EncryptedDateField, EncryptedTextField


class UserManager(BaseUserManager):
    """Create users with email as their login identifier."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_staff and is_superuser set to True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    phone_number = models.CharField(max_length=32, blank=True)
    department = models.CharField(max_length=120, blank=True)
    specialization = models.CharField(max_length=120, blank=True)
    license_number = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.user.email}"


class Organization(models.Model):
    class Plan(models.TextChoices):
        FREE = "free", "Free"
        PRO = "pro", "Pro"

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160, unique=True)
    plan = models.CharField(max_length=16, choices=Plan.choices, default=Plan.FREE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        DOCTOR = "doctor", "Doctor"
        STAFF = "staff", "Staff"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "organization"), name="unique_user_org_membership"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"


class OrganizationInvitation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Membership.Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_active(self):
        return self.accepted_at is None and self.expires_at > timezone.now()

    def __str__(self):
        return f"Invitation for {self.email} to {self.organization}"


def generate_patient_mrn():
    return f"P-{uuid.uuid4().hex[:12].upper()}"


class Patient(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        OTHER = "other", "Other / non-binary"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INPATIENT = "inpatient", "Inpatient"
        DISCHARGED = "discharged", "Discharged"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="patients")
    medical_record_number = models.CharField(max_length=32, default=generate_patient_mrn)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    date_of_birth = EncryptedDateField()
    gender = models.CharField(max_length=16, choices=Gender.choices)
    phone = EncryptedCharField(max_length=32, blank=True)
    primary_doctor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_patients",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("last_name", "first_name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "medical_record_number"),
                name="unique_org_patient_mrn",
            ),
        ]
        indexes = [models.Index(fields=("organization", "status"), name="patient_org_status_idx")]

    def __str__(self):
        return f"{self.last_name}, {self.first_name} ({self.medical_record_number})"


class Encounter(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="encounters")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="encounters")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_encounters")
    assigned_doctor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_encounters",
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETED)
    chief_complaint = EncryptedTextField()
    blood_pressure = EncryptedTextField(blank=True)
    heart_rate = EncryptedTextField(blank=True)
    temperature = EncryptedTextField(blank=True)
    oxygen_saturation = EncryptedTextField(blank=True)
    objective_notes = EncryptedTextField(blank=True)
    assessment = EncryptedTextField(blank=True)
    plan = EncryptedTextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-occurred_at", "-id")
        indexes = [
            models.Index(fields=("organization", "occurred_at"), name="encounter_org_date_idx"),
            models.Index(fields=("organization", "status"), name="encounter_org_status_idx"),
        ]

    def __str__(self):
        return f"Encounter {self.pk} for {self.patient}"


def audit_entry_digest(*, organization_id, sequence, actor_user_id, action, object_type,
                       object_id, metadata, created_at, previous_hash):
    payload = {
        "organization_id": organization_id,
        "sequence": sequence,
        "actor_user_id": actor_user_id,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "metadata": metadata,
        "created_at": created_at.isoformat(),
        "previous_hash": previous_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ImmutableAuditEventQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        raise TypeError("Audit events must be appended individually through the audit service.")

    def update(self, **kwargs):
        raise TypeError("Audit events are append-only.")

    def delete(self):
        raise TypeError("Audit events are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise TypeError("Audit events are append-only.")


class AuditEvent(models.Model):
    """Tamper-evident event metadata; clinical field values must never be stored here."""

    GENESIS_HASH = "0" * 64

    organization_id = models.PositiveBigIntegerField()
    sequence = models.PositiveBigIntegerField()
    actor_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    previous_hash = models.CharField(max_length=64)
    entry_hash = models.CharField(max_length=64)

    objects = ImmutableAuditEventQuerySet.as_manager()

    class Meta:
        ordering = ("organization_id", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("organization_id", "sequence"), name="unique_audit_org_sequence",
            ),
        ]
        indexes = [
            models.Index(fields=("organization_id", "created_at"), name="audit_org_created_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise TypeError("Audit events are append-only.")
        expected_hash = audit_entry_digest(
            organization_id=self.organization_id,
            sequence=self.sequence,
            actor_user_id=self.actor_user_id,
            action=self.action,
            object_type=self.object_type,
            object_id=self.object_id,
            metadata=self.metadata,
            created_at=self.created_at,
            previous_hash=self.previous_hash,
        )
        if self.entry_hash != expected_hash:
            raise ValueError("Audit event hash does not match its contents.")
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("Audit events are append-only.")
