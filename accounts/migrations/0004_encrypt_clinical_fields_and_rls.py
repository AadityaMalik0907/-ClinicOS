from django.db import migrations
from django.conf import settings
from cryptography.fernet import Fernet
import accounts.fields


PATIENT_POLICY = """
CREATE POLICY patient_tenant_isolation ON accounts_patient
USING (
  current_setting('clinicos.is_superuser', true) = 'true'
  OR (
    organization_id = NULLIF(current_setting('clinicos.organization_id', true), '')::bigint
    AND EXISTS (
      SELECT 1 FROM accounts_membership m
      WHERE m.organization_id = accounts_patient.organization_id
        AND m.user_id = NULLIF(current_setting('clinicos.user_id', true), '')::bigint
    )
  )
)
WITH CHECK (
  current_setting('clinicos.is_superuser', true) = 'true'
  OR (
    organization_id = NULLIF(current_setting('clinicos.organization_id', true), '')::bigint
    AND EXISTS (
      SELECT 1 FROM accounts_membership m
      WHERE m.organization_id = accounts_patient.organization_id
        AND m.user_id = NULLIF(current_setting('clinicos.user_id', true), '')::bigint
    )
  )
)
"""

ENCOUNTER_POLICY = """
CREATE POLICY encounter_tenant_isolation ON accounts_encounter
USING (
  current_setting('clinicos.is_superuser', true) = 'true'
  OR (
    organization_id = NULLIF(current_setting('clinicos.organization_id', true), '')::bigint
    AND EXISTS (
      SELECT 1 FROM accounts_membership m
      WHERE m.organization_id = accounts_encounter.organization_id
        AND m.user_id = NULLIF(current_setting('clinicos.user_id', true), '')::bigint
    )
  )
)
WITH CHECK (
  current_setting('clinicos.is_superuser', true) = 'true'
  OR (
    organization_id = NULLIF(current_setting('clinicos.organization_id', true), '')::bigint
    AND EXISTS (
      SELECT 1 FROM accounts_membership m
      WHERE m.organization_id = accounts_encounter.organization_id
        AND m.user_id = NULLIF(current_setting('clinicos.user_id', true), '')::bigint
    )
  )
)
"""


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table, policy in (("accounts_patient", PATIENT_POLICY), ("accounts_encounter", ENCOUNTER_POLICY)):
            cursor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            cursor.execute(policy)


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP POLICY IF EXISTS encounter_tenant_isolation ON accounts_encounter")
        cursor.execute("DROP POLICY IF EXISTS patient_tenant_isolation ON accounts_patient")
        cursor.execute("ALTER TABLE accounts_encounter NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE accounts_encounter DISABLE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE accounts_patient NO FORCE ROW LEVEL SECURITY")
        cursor.execute("ALTER TABLE accounts_patient DISABLE ROW LEVEL SECURITY")


def encrypt_existing_records(apps, schema_editor):
    transform_existing_records(apps, schema_editor, decrypt=False)


def decrypt_existing_records(apps, schema_editor):
    """Restore plaintext before Django changes the columns back to ordinary fields."""
    transform_existing_records(apps, schema_editor, decrypt=True)


def transform_existing_records(apps, schema_editor, decrypt):
    connection = schema_editor.connection
    Patient = apps.get_model("accounts", "Patient")
    Encounter = apps.get_model("accounts", "Encounter")
    cipher = Fernet(settings.FIELD_ENCRYPTION_KEY.encode("ascii") if isinstance(settings.FIELD_ENCRYPTION_KEY, str)
                    else settings.FIELD_ENCRYPTION_KEY)
    prefix = "fernet:v1:"
    with connection.cursor() as read_cursor, connection.cursor() as write_cursor:
        for model, fields in (
            (Patient, ("date_of_birth", "phone")),
            (Encounter, (
                "chief_complaint", "blood_pressure", "heart_rate", "temperature",
                "oxygen_saturation", "objective_notes", "assessment", "plan",
            )),
        ):
            quote = connection.ops.quote_name
            table = quote(model._meta.db_table)
            columns = [model._meta.pk.column, *(model._meta.get_field(name).column for name in fields)]
            read_cursor.execute(f"SELECT {', '.join(quote(name) for name in columns)} FROM {table}")
            rows = read_cursor.fetchmany(200)
            while rows:
                for row in rows:
                    record_id, *values = row
                    transformed = []
                    for value in values:
                        if value is None or value == "":
                            transformed.append(value)
                        elif decrypt:
                            raw = str(value)
                            if not raw.startswith(prefix):
                                raise ValueError("Expected encrypted clinical data while reversing migration.")
                            transformed.append(cipher.decrypt(raw[len(prefix):].encode("ascii")).decode("utf-8"))
                        else:
                            transformed.append(prefix + cipher.encrypt(str(value).encode("utf-8")).decode("ascii"))
                    assignments = ", ".join(f"{quote(model._meta.get_field(name).column)} = %s" for name in fields)
                    write_cursor.execute(
                        f"UPDATE {table} SET {assignments} WHERE {quote(model._meta.pk.column)} = %s",
                        [*transformed, record_id],
                    )
                rows = read_cursor.fetchmany(200)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_patient_encounter")]

    operations = [
        migrations.AlterField(
            model_name="patient", name="date_of_birth",
            field=accounts.fields.EncryptedDateField(),
        ),
        migrations.AlterField(
            model_name="patient", name="phone",
            field=accounts.fields.EncryptedCharField(blank=True, max_length=32),
        ),
        migrations.AlterField(
            model_name="encounter", name="chief_complaint",
            field=accounts.fields.EncryptedTextField(),
        ),
        *[
            migrations.AlterField(
                model_name="encounter", name=name,
                field=accounts.fields.EncryptedTextField(blank=True),
            )
            for name in (
                "blood_pressure", "heart_rate", "temperature", "oxygen_saturation",
                "objective_notes", "assessment", "plan",
            )
        ],
        migrations.RunPython(encrypt_existing_records, decrypt_existing_records),
        migrations.RunPython(enable_rls, disable_rls),
    ]
