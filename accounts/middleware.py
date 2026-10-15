from django.db import connection, transaction
from django.core.exceptions import ImproperlyConfigured


class PostgresRLSContextMiddleware:
    """Set transaction-local tenant identity for PostgreSQL row security policies."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if connection.vendor != "postgresql":
            return self.get_response(request)

        with transaction.atomic():
            if not getattr(connection, "clinicos_rls_verified", False):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT r.rolsuper, r.rolbypassrls, "
                        "COALESCE(bool_and(c.relrowsecurity AND c.relforcerowsecurity), false), "
                        "(SELECT count(*) = 4 FROM pg_policies p "
                        " WHERE p.schemaname = current_schema() AND ("
                        " (p.tablename = 'accounts_patient' AND p.policyname = 'patient_tenant_isolation') "
                        " OR (p.tablename = 'accounts_encounter' AND p.policyname = 'encounter_tenant_isolation') "
                        " OR (p.tablename = 'accounts_auditevent' AND p.policyname = 'audit_tenant_isolation') "
                        " OR (p.tablename = 'accounts_usageevent' AND p.policyname = 'usage_tenant_isolation')) ) "
                        "FROM pg_roles r CROSS JOIN pg_class c "
                        "WHERE r.rolname = current_user AND c.oid IN "
                        " ('accounts_patient'::regclass, 'accounts_encounter'::regclass, "
                        "  'accounts_auditevent'::regclass, 'accounts_usageevent'::regclass) "
                        "GROUP BY r.rolsuper, r.rolbypassrls"
                    )
                    role_is_superuser, role_bypasses_rls, policies_enabled, policies_exist = cursor.fetchone()
                if role_is_superuser or role_bypasses_rls:
                    raise ImproperlyConfigured(
                        "PostgreSQL application connections must use a non-superuser role without BYPASSRLS."
                    )
                if not policies_enabled or not policies_exist:
                    raise ImproperlyConfigured(
                        "PostgreSQL tenant RLS policies are missing; run database migrations."
                    )
                connection.clinicos_rls_verified = True

            user = request.user
            user_id = str(user.pk) if user.is_authenticated else ""
            is_superuser = "true" if user.is_authenticated and user.is_superuser else "false"
            organization_id = request.session.get("active_organization_id", "")
            if not str(organization_id).isdigit():
                organization_id = ""
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('clinicos.user_id', %s, true), "
                    "set_config('clinicos.organization_id', %s, true), "
                    "set_config('clinicos.is_superuser', %s, true)",
                    [user_id, str(organization_id), is_superuser],
                )
            return self.get_response(request)
