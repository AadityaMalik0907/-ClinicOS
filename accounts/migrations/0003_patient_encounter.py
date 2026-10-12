import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import accounts.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0002_organizationinvitation_userprofile"),
    ]

    operations = [
        migrations.CreateModel(
            name="Patient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("medical_record_number", models.CharField(default=accounts.models.generate_patient_mrn, max_length=32)),
                ("first_name", models.CharField(max_length=150)),
                ("last_name", models.CharField(max_length=150)),
                ("date_of_birth", models.DateField()),
                ("gender", models.CharField(choices=[("female", "Female"), ("male", "Male"), ("other", "Other / non-binary")], max_length=16)),
                ("phone", models.CharField(blank=True, max_length=32)),
                ("status", models.CharField(choices=[("active", "Active"), ("inpatient", "Inpatient"), ("discharged", "Discharged")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="patients", to="accounts.organization")),
                ("primary_doctor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="primary_patients", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("last_name", "first_name", "id"),
                "indexes": [models.Index(fields=["organization", "status"], name="patient_org_status_idx")],
            },
        ),
        migrations.CreateModel(
            name="Encounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("status", models.CharField(choices=[("scheduled", "Scheduled"), ("in_progress", "In progress"), ("completed", "Completed")], default="completed", max_length=16)),
                ("chief_complaint", models.TextField()),
                ("blood_pressure", models.CharField(blank=True, max_length=32)),
                ("heart_rate", models.CharField(blank=True, max_length=32)),
                ("temperature", models.CharField(blank=True, max_length=32)),
                ("oxygen_saturation", models.CharField(blank=True, max_length=32)),
                ("objective_notes", models.TextField(blank=True)),
                ("assessment", models.TextField(blank=True)),
                ("plan", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_doctor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_encounters", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_encounters", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="encounters", to="accounts.organization")),
                ("patient", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="encounters", to="accounts.patient")),
            ],
            options={
                "ordering": ("-occurred_at", "-id"),
                "indexes": [
                    models.Index(fields=["organization", "occurred_at"], name="encounter_org_date_idx"),
                    models.Index(fields=["organization", "status"], name="encounter_org_status_idx"),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="patient",
            constraint=models.UniqueConstraint(fields=("organization", "medical_record_number"), name="unique_org_patient_mrn"),
        ),
    ]
