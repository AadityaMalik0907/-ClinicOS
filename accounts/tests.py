from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase
from cryptography.fernet import Fernet

from .fields import EncryptedFieldError
from .audit import append_audit_event
from .models import AuditEvent, Encounter, Membership, Organization, Patient


User = get_user_model()


class EncryptedClinicalFieldTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="encryption@example.com", password="SafePassword!2026")
        self.organization = Organization.objects.create(name="Encryption Clinic", slug="encryption-clinic")

    def test_patient_and_encounter_fields_are_encrypted_at_rest_and_decrypted_by_orm(self):
        patient = Patient.objects.create(
            organization=self.organization,
            first_name="Rae",
            last_name="Test",
            date_of_birth=date(1990, 4, 5),
            gender=Patient.Gender.OTHER,
            phone="555-0123",
        )
        encounter = Encounter.objects.create(
            organization=self.organization,
            patient=patient,
            created_by=self.user,
            chief_complaint="Persistent headache",
            blood_pressure="120/80",
            heart_rate="72 bpm",
            temperature="37 C",
            oxygen_saturation="98%",
            objective_notes="No acute distress",
            assessment="Tension headache",
            plan="Follow up in one week",
        )

        with connection.cursor() as cursor:
            cursor.execute("SELECT date_of_birth, phone FROM accounts_patient WHERE id = %s", [patient.pk])
            stored_patient_values = cursor.fetchone()
            cursor.execute(
                "SELECT chief_complaint, blood_pressure, heart_rate, temperature, oxygen_saturation, "
                "objective_notes, assessment, plan FROM accounts_encounter WHERE id = %s",
                [encounter.pk],
            )
            stored_encounter_values = cursor.fetchone()

        for stored_value in (*stored_patient_values, *stored_encounter_values):
            self.assertTrue(stored_value.startswith("fernet:v1:"))
        self.assertNotIn("555-0123", stored_patient_values)
        self.assertNotIn("Persistent headache", stored_encounter_values)

        patient.refresh_from_db()
        encounter.refresh_from_db()
        self.assertEqual(patient.date_of_birth, date(1990, 4, 5))
        self.assertEqual(patient.phone, "555-0123")
        self.assertEqual(encounter.chief_complaint, "Persistent headache")
        self.assertEqual(encounter.plan, "Follow up in one week")

    def test_encrypted_fields_reject_plaintext_database_lookups(self):
        with self.assertRaises(FieldError):
            Patient.objects.filter(phone__icontains="555").exists()

    def test_wrong_encryption_key_fails_closed(self):
        patient = Patient.objects.create(
            organization=self.organization,
            first_name="Key",
            last_name="Check",
            date_of_birth=date(1988, 1, 2),
            gender=Patient.Gender.OTHER,
            phone="555-0199",
        )
        ciphertext_key = Fernet.generate_key()
        wrong_key = Fernet.generate_key()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE accounts_patient SET phone = %s WHERE id = %s",
                ["fernet:v1:" + Fernet(ciphertext_key).encrypt(b"555-0199").decode("ascii"), patient.pk],
            )
        with self.settings(FIELD_ENCRYPTION_KEY=wrong_key.decode("ascii")):
            with self.assertRaises(EncryptedFieldError):
                Patient.objects.get(pk=patient.pk)


class PhaseFourDataMigrationTests(TransactionTestCase):
    """Exercise existing-row encryption and reverse migration against SQLite."""

    migrate_from = ("accounts", "0003_patient_encounter")
    migrate_to = ("accounts", "0004_encrypt_clinical_fields_and_rls")

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        UserModel = old_apps.get_model("accounts", "User")
        OrganizationModel = old_apps.get_model("accounts", "Organization")
        PatientModel = old_apps.get_model("accounts", "Patient")
        EncounterModel = old_apps.get_model("accounts", "Encounter")

        user = UserModel.objects.create(email="migration@example.com", password="not-used")
        organization = OrganizationModel.objects.create(name="Migration Clinic", slug="migration-clinic")
        patient = PatientModel.objects.create(
            organization=organization,
            first_name="Legacy",
            last_name="Patient",
            date_of_birth=date(1975, 6, 7),
            gender="other",
            phone="555-legacy",
        )
        encounter = EncounterModel.objects.create(
            organization=organization,
            patient=patient,
            created_by=user,
            chief_complaint="Legacy complaint",
            blood_pressure="118/76",
            heart_rate="70",
            temperature="36.8 C",
            oxygen_saturation="99%",
            objective_notes="Legacy examination",
            assessment="Legacy assessment",
            plan="Legacy plan",
        )
        self.patient_id = patient.pk
        self.encounter_id = encounter.pk
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_existing_clinical_values_are_encrypted_and_migration_reverses_cleanly(self):
        current_apps = MigrationExecutor(connection).loader.project_state([self.migrate_to]).apps
        PatientModel = current_apps.get_model("accounts", "Patient")
        EncounterModel = current_apps.get_model("accounts", "Encounter")
        patient = PatientModel.objects.get(pk=self.patient_id)
        encounter = EncounterModel.objects.get(pk=self.encounter_id)
        self.assertEqual(patient.date_of_birth, date(1975, 6, 7))
        self.assertEqual(patient.phone, "555-legacy")
        self.assertEqual(encounter.chief_complaint, "Legacy complaint")
        with connection.cursor() as cursor:
            cursor.execute("SELECT phone FROM accounts_patient WHERE id = %s", [self.patient_id])
            self.assertTrue(cursor.fetchone()[0].startswith("fernet:v1:"))

        MigrationExecutor(connection).migrate([self.migrate_from])
        old_apps = MigrationExecutor(connection).loader.project_state([self.migrate_from]).apps
        restored_patient = old_apps.get_model("accounts", "Patient").objects.get(pk=self.patient_id)
        restored_encounter = old_apps.get_model("accounts", "Encounter").objects.get(pk=self.encounter_id)
        self.assertEqual(restored_patient.phone, "555-legacy")
        self.assertEqual(restored_patient.date_of_birth, date(1975, 6, 7))
        self.assertEqual(restored_encounter.chief_complaint, "Legacy complaint")


class AuditLogTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="audit-owner@example.com", password="SafePassword!2026")
        self.viewer = User.objects.create_user(email="audit-viewer@example.com", password="SafePassword!2026")
        self.organization = Organization.objects.create(name="Audit Clinic", slug="audit-clinic")
        Membership.objects.create(
            user=self.owner, organization=self.organization, role=Membership.Role.OWNER,
        )
        Membership.objects.create(
            user=self.viewer, organization=self.organization, role=Membership.Role.VIEWER,
        )
        session = self.client.session
        session["active_organization_id"] = self.organization.pk
        session.save()
        self.client.force_authenticate(self.owner)

    def test_patient_reads_and_writes_append_verified_events_without_clinical_values(self):
        created = self.client.post(
            "/api/v1/patients/",
            {
                "first_name": "Audit",
                "last_name": "Subject",
                "date_of_birth": "1990-01-02",
                "gender": "other",
                "phone": "555-secret",
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        patient_id = created.data["id"]
        event = AuditEvent.objects.get(sequence=1)
        self.assertEqual(event.action, "patient.created")
        self.assertEqual(event.object_id, str(patient_id))
        self.assertEqual(event.metadata, {})
        self.assertNotIn("555-secret", str(event.metadata))

        read = self.client.get(f"/api/v1/patients/{patient_id}/")
        self.assertEqual(read.status_code, status.HTTP_200_OK)
        self.assertEqual(AuditEvent.objects.count(), 2)
        verified = self.client.get("/api/v1/audit/verify/")
        self.assertEqual(verified.status_code, status.HTTP_200_OK)
        self.assertEqual(verified.data, {
            "valid": True, "checked_entries": 2, "first_invalid_sequence": None,
        })

    def test_verification_detects_tampering_and_audit_rows_are_immutable(self):
        append_audit_event(
            organization_id=self.organization.pk,
            actor_user_id=self.owner.pk,
            action="patient.read",
            object_type="patient",
            object_id="123",
        )
        event = AuditEvent.objects.get()
        with self.assertRaises(TypeError):
            AuditEvent.objects.filter(pk=event.pk).update(action="tampered")
        with self.assertRaises(TypeError):
            event.delete()

        with connection.cursor() as cursor:
            cursor.execute("UPDATE accounts_auditevent SET action = %s WHERE id = %s", ["tampered", event.pk])
        response = self.client.get("/api/v1/audit/verify/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["first_invalid_sequence"], 1)

    def test_viewer_cannot_verify_audit_chain(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get("/api/v1/audit/verify/").status_code, status.HTTP_403_FORBIDDEN)


class AuthenticationApiTests(APITestCase):
    def setUp(self):
        self.registration = {
            "email": "clinician@example.com",
            "password": "SafePassword!2026",
            "first_name": "Alex",
            "last_name": "Morgan",
        }

    def test_registers_user_with_hashed_password(self):
        response = self.client.post("/api/v1/auth/register/", self.registration, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email="clinician@example.com")
        self.assertTrue(user.check_password(self.registration["password"]))
        self.assertNotEqual(user.password, self.registration["password"])
        self.assertEqual(response.data["email"], self.registration["email"])
        self.assertNotIn("password", response.data)

    def test_duplicate_email_returns_consistent_error(self):
        User.objects.create_user(email=self.registration["email"], password="AnotherPassword!2026")

        response = self.client.post("/api/v1/auth/register/", self.registration, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("email", response.data["error"]["fields"])

    def test_login_me_and_logout_use_session(self):
        user = User.objects.create_user(
            email=self.registration["email"], password=self.registration["password"]
        )

        login_response = self.client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": self.registration["password"]},
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn("sessionid", self.client.cookies)

        me_response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data["email"], user.email)

        logout_response = self.client.post("/api/v1/auth/logout/", {}, format="json")
        self.assertEqual(logout_response.status_code, status.HTTP_204_NO_CONTENT)
        # Django session authentication returns 403 for an anonymous session.
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_login_does_not_disclose_account_existence(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "unknown@example.com", "password": "WrongPassword!2026"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"error": {"code": "validation_error", "message": "Invalid email or password."}})


class OrganizationPhaseOneTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", password="OwnerPassword!2026")
        self.member = User.objects.create_user(email="member@example.com", password="MemberPassword!2026")
        self.client.force_authenticate(self.owner)

    def test_owner_can_create_organization_and_current_user_lists_role(self):
        response = self.client.post(
            "/api/v1/organizations/",
            {"name": "Green Valley Clinic", "slug": "green-valley"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        organization = Organization.objects.get(slug="green-valley")
        membership = Membership.objects.get(user=self.owner, organization=organization)
        self.assertEqual(membership.role, Membership.Role.OWNER)

        me = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertEqual(me.data["memberships"][0]["role"], Membership.Role.OWNER)
        self.assertEqual(me.data["profile"]["department"], "")

    def test_profile_can_be_updated(self):
        response = self.client.patch(
            "/api/v1/profile/",
            {"department": "Cardiology", "specialization": "Interventional"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["department"], "Cardiology")
        self.assertEqual(self.owner.profile.specialization, "Interventional")

    def test_owner_can_invite_member_and_invited_email_can_accept(self):
        create_response = self.client.post(
            "/api/v1/organizations/",
            {"name": "Invite Clinic", "slug": "invite-clinic"},
            format="json",
        )
        organization_id = create_response.data["id"]
        invite_response = self.client.post(
            f"/api/v1/organizations/{organization_id}/invitations/",
            {"email": self.member.email, "role": Membership.Role.DOCTOR},
            format="json",
        )
        self.assertEqual(invite_response.status_code, status.HTTP_201_CREATED)
        token = invite_response.data["token"]

        self.client.force_authenticate(self.member)
        accept_response = self.client.post(
            "/api/v1/invitations/accept/", {"token": token}, format="json"
        )
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)
        self.assertEqual(accept_response.data["role"], Membership.Role.DOCTOR)

        self.client.force_authenticate(self.owner)
        role_response = self.client.patch(
            f"/api/v1/organizations/{organization_id}/members/{self.member.id}/",
            {"role": Membership.Role.STAFF},
            format="json",
        )
        self.assertEqual(role_response.status_code, status.HTTP_200_OK)
        self.assertEqual(role_response.data["role"], Membership.Role.STAFF)
        remove_response = self.client.delete(
            f"/api/v1/organizations/{organization_id}/members/{self.member.id}/"
        )
        self.assertEqual(remove_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            Membership.objects.filter(user=self.member, organization_id=organization_id).exists()
        )

    def test_user_cannot_view_another_organizations_details(self):
        organization = Organization.objects.create(name="Private Clinic", slug="private-clinic")
        self.client.force_authenticate(self.member)

        response = self.client.get(f"/api/v1/organizations/{organization.id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ClinicalApiPhaseThreeTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="clinical-owner@example.com", password="OwnerPassword!2026")
        self.doctor = User.objects.create_user(email="clinical-doctor@example.com", password="DoctorPassword!2026")
        self.viewer = User.objects.create_user(email="clinical-viewer@example.com", password="ViewerPassword!2026")
        self.other_user = User.objects.create_user(email="other-clinic@example.com", password="OtherPassword!2026")
        self.organization = Organization.objects.create(name="North Clinic", slug="north-clinic")
        self.other_organization = Organization.objects.create(name="South Clinic", slug="south-clinic")
        Membership.objects.create(user=self.owner, organization=self.organization, role=Membership.Role.OWNER)
        Membership.objects.create(user=self.doctor, organization=self.organization, role=Membership.Role.DOCTOR)
        Membership.objects.create(user=self.viewer, organization=self.organization, role=Membership.Role.VIEWER)
        Membership.objects.create(user=self.other_user, organization=self.other_organization, role=Membership.Role.OWNER)
        self.client.force_authenticate(self.owner)
        self.select_organization(self.organization)

    def select_organization(self, organization):
        session = self.client.session
        session["active_organization_id"] = organization.id
        session.save()

    def create_patient(self, **overrides):
        payload = {
            "first_name": "Avery",
            "last_name": "Patient",
            "date_of_birth": "1990-04-15",
            "gender": Patient.Gender.OTHER,
            "phone": "+91 9876543210",
        }
        payload.update(overrides)
        return self.client.post("/api/v1/patients/", payload, format="json")

    def create_encounter(self, patient_id):
        return self.client.post(
            "/api/v1/encounters/",
            {
                "patient_id": patient_id,
                "chief_complaint": "Annual follow-up",
                "assessment": "Stable",
                "plan": "Continue current care",
            },
            format="json",
        )

    def test_patient_create_search_filter_update_and_delete(self):
        created = self.create_patient()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertTrue(created.data["mrn"].startswith("P-"))
        patient = Patient.objects.get(pk=created.data["id"])
        self.assertEqual(patient.organization, self.organization)

        search = self.client.get("/api/v1/patients/?search=Avery&status=active")
        self.assertEqual(search.status_code, status.HTTP_200_OK)
        self.assertEqual(search.data["count"], 1)

        updated = self.client.patch(
            f"/api/v1/patients/{patient.id}/",
            {"status": Patient.Status.DISCHARGED},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["status"], Patient.Status.DISCHARGED)

        deleted = self.client.delete(f"/api/v1/patients/{patient.id}/")
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Patient.objects.filter(pk=patient.id).exists())

    def test_patient_and_encounter_records_are_isolated_by_active_organization(self):
        patient_response = self.create_patient()
        own_patient_id = patient_response.data["id"]
        foreign_patient = Patient.objects.create(
            organization=self.other_organization,
            first_name="Private",
            last_name="Record",
            date_of_birth="1980-01-01",
            gender=Patient.Gender.OTHER,
        )
        foreign_encounter = Encounter.objects.create(
            organization=self.other_organization,
            patient=foreign_patient,
            created_by=self.other_user,
            chief_complaint="Private note",
        )

        self.assertEqual(
            self.client.get(f"/api/v1/patients/{foreign_patient.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/patients/{foreign_patient.id}/",
                {"first_name": "Changed"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/encounters/",
                {"patient_id": foreign_patient.id, "chief_complaint": "Cross-tenant attempt"},
                format="json",
            ).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        own_encounter = self.create_encounter(own_patient_id)
        self.assertEqual(own_encounter.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            self.client.get(f"/api/v1/encounters/{foreign_encounter.id}/").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get("/api/v1/encounters/").data["count"],
            1,
        )

    def test_encounter_crud_and_patient_protection(self):
        patient = self.create_patient()
        encounter = self.create_encounter(patient.data["id"])
        self.assertEqual(encounter.status_code, status.HTTP_201_CREATED)
        encounter_id = encounter.data["id"]

        update = self.client.patch(
            f"/api/v1/encounters/{encounter_id}/",
            {"assessment": "Updated assessment"},
            format="json",
        )
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(update.data["assessment"], "Updated assessment")

        patient_delete = self.client.delete(f"/api/v1/patients/{patient.data['id']}/")
        self.assertEqual(patient_delete.status_code, status.HTTP_409_CONFLICT)

        encounter_delete = self.client.delete(f"/api/v1/encounters/{encounter_id}/")
        self.assertEqual(encounter_delete.status_code, status.HTTP_204_NO_CONTENT)

    def test_viewer_can_read_but_cannot_change_clinical_records(self):
        patient = self.create_patient()
        self.client.force_authenticate(self.viewer)

        self.assertEqual(self.client.get("/api/v1/patients/").status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(
                "/api/v1/patients/",
                {"first_name": "No", "last_name": "Write", "date_of_birth": "2000-01-01", "gender": "other"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/patients/{patient.data['id']}/",
                {"first_name": "No"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_clinical_endpoints_require_an_active_organization(self):
        session = self.client.session
        session.pop("active_organization_id", None)
        session.save()

        response = self.client.get("/api/v1/patients/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")
