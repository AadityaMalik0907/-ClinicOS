# Phase 7 security and benchmark procedure

## Tenant isolation checks

Run the focused attack suite and the full Django test suite from the repository root:

```powershell
.venv\Scripts\python.exe manage.py test accounts.tests.CrossTenantAttackTests
.venv\Scripts\python.exe manage.py test
```

The suite attempts tenant selection through query parameters and forged payloads, reads/updates/deletes foreign patient and encounter IDs, links a foreign patient to a new encounter, and changes the session to an organization without membership. It also checks that audit verification and usage summaries stay scoped to the selected membership.

## HTTP load run

Use a development or staging server with synthetic patients only. Create an account that belongs to the target organization and can view its patient list. Applying migrations is required before Phase 6 usage endpoints are available. Each requested patient-list page adds an audit event, so the command requires explicit acknowledgement:

```powershell
$env:CLINICOS_BENCH_EMAIL = "benchmark@example.test"
$env:CLINICOS_BENCH_PASSWORD = "<local synthetic-account password>"
.venv\Scripts\python.exe scripts/load_test.py --base-url http://127.0.0.1:8000 --organization-id 1 --requests 100 --workers 8 --allow-audit-writes
```

The runner logs in through the session and CSRF-protected API, selects the organization, issues concurrent GET requests to `/api/v1/patients/?page_size=50`, then prints JSON containing latency percentiles, throughput, elapsed time, and HTTP status counts. It does not print credentials or response bodies. Keep request volume modest on a shared environment; the default user throttle allows 1000 requests per hour.

## Benchmark record

No live HTTP benchmark has been measured in this checkout. Do not treat an example run or a SQLite result as a production performance claim. For each published run, preserve the JSON output and record:

- Git commit and date/time (UTC)
- Database engine/version and whether the database is local or remote
- Web worker count, host CPU/memory, cache backend, and relevant settings
- Synthetic patient count and test data generation method
- Request count, worker count, HTTP status counts, throughput, and p50/p95/p99 latency
- Whether PostgreSQL RLS is enabled and which database role served requests

Run PostgreSQL measurements with the production-like non-superuser application role. SQLite does not exercise PostgreSQL row-level security. Never use real patient data for load testing.
