"""Prepare the configured database cache table before a Vercel release."""

import os
import sys
from pathlib import Path

# Running this file directly puts scripts/ on sys.path, not the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection


DATABASE_CACHE_BACKEND = "django.core.cache.backends.db.DatabaseCache"


def ensure_cache_table():
    """Create only the configured database cache table when it is absent."""
    cache_config = settings.CACHES["default"]
    if cache_config.get("BACKEND") != DATABASE_CACHE_BACKEND:
        raise CommandError(
            "The default cache backend is not DatabaseCache. Set DJANGO_DEBUG=false "
            "and configure the deployment cache before running this release step."
        )

    table_name = cache_config.get("LOCATION")
    if not table_name:
        raise CommandError("The default database cache must have a table name in LOCATION.")

    try:
        connection.ensure_connection()
        existing_tables = connection.introspection.table_names()
    except DatabaseError as exc:
        raise CommandError(f"Could not connect to the configured database: {exc}") from exc

    if table_name in existing_tables:
        print(f"Cache table '{table_name}' already exists; no changes made.")
        return False

    try:
        call_command("createcachetable", table_name, verbosity=0)
    except DatabaseError as exc:
        raise CommandError(f"Could not create cache table '{table_name}': {exc}") from exc

    print(f"Created cache table '{table_name}'.")
    return True


def main():
    import django

    django.setup()
    try:
        ensure_cache_table()
    except CommandError as exc:
        print(f"Vercel release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
