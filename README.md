# ClinicOS

ClinicOS is a learning project for a multi-tenant healthcare SaaS backend built with Django, Django REST Framework, and PostgreSQL. It uses synthetic data only.

## Learning approach

We will build one working slice at a time. For each slice, we will cover the problem it solves, the design choice, the tradeoffs, and how to explain it in an interview. Security requirements such as tenant isolation will be enforced at multiple layers rather than left as a convention.

## Current foundation

- Django project and DRF installed
- PostgreSQL development service via Docker Compose
- Custom email-based user model
- Organization and membership models, with a unique membership per user and organization

## Run locally (Windows)

Create and activate a virtual environment, then install requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The checked-out `.env` uses SQLite so the app runs without a separate database service. Create tables and an admin login, then start Django:

```powershell
python manage.py makemigrations accounts
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/`. To use PostgreSQL instead, start Docker Desktop and run `docker compose up --build`; Compose configures the web service to use its PostgreSQL container.

The default database password and Django secret are for local development only. Do not deploy them. Do not put real patient information in this project.

## Planned milestones

1. Account and organization foundation, registration, organization creation, and JWT login.
2. Patient and encounter CRUD with tenant scoping and IDOR protection.
3. Central RBAC permission map, invites, and role management.
4. PostgreSQL row-level security and application-level field encryption.
5. Append-only, hash-chained audit log and verification endpoint.
6. Usage metering, plan limits, and rate limiting.
7. Cross-tenant attack suite, load testing, and documented benchmarks.

Success metrics will be reported only after they are measured: tenant-isolation test count, audit tamper checks, and patient-list latency under a documented workload.
