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

Open `http://127.0.0.1:8000/login/` to use the sign-in and account-creation page. The homepage at `http://127.0.0.1:8000/` sends signed-out visitors to login. Open `http://127.0.0.1:8000/admin/` for the Django administration site. To use PostgreSQL instead, start Docker Desktop and run `docker compose up --build`; Compose configures the web service to use its PostgreSQL container.

The default database password and Django secret are for local development only. Do not deploy them. Do not put real patient information in this project.

For PostgreSQL Compose, the database bootstrap account creates a separate `clinicos_app` role with `NOSUPERUSER` and `NOBYPASSRLS`; the web service connects with that role. Keep the bootstrap credentials for database administration and use a separate application password in deployed environments.

## Account API (backend)

The backend supports many accounts: each registration creates a separate row in the custom `accounts.User` table, and each email address can belong to one account. Passwords are hashed by Django; they are never returned by the API. Registration currently creates an account only. Organization creation and invitations can be added separately.

Before a browser sends a POST request, fetch `/api/auth/csrf/` to receive the CSRF cookie. Send that cookie back as the `X-CSRFToken` header on POST requests. Keep cookies enabled and use `credentials: "include"` in browser `fetch` calls. The API uses Django session cookies, so the browser does not need to store a password or a JWT.

New API clients should use the versioned paths under `/api/v1/`. The older `/api/auth/` paths remain available for the current browser frontend. Phase 0 keeps session authentication because this application currently uses a browser and secure HTTP-only session cookies; JWT can be introduced later if mobile or third-party clients require stateless tokens.

| Method and path | Purpose |
| --- | --- |
| `GET /api/auth/csrf/` | Set the CSRF cookie for browser requests |
| `POST /api/auth/register/` | Create an account from JSON `{ "email", "password", "first_name", "last_name" }` |
| `POST /api/auth/login/` | Sign in with JSON `{ "email", "password" }`; sets a session cookie |
| `POST /api/auth/logout/` | End the current session |
| `GET /api/auth/me/` | Return the signed-in account, or an authorization error |

The equivalent versioned paths are `/api/v1/auth/csrf/`, `/api/v1/auth/register/`, `/api/v1/auth/login/`, `/api/v1/auth/logout/`, and `/api/v1/auth/me/`. API errors use a predictable shape, for example:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "fields": {"email": ["An account with this email already exists."]}
  }
}
```

Registration applies Django's configured password validators and rejects duplicate emails. Login errors do not disclose whether an email exists. For local development, run `python manage.py migrate` before using the endpoints; the current account model is already represented by the initial accounts migration.

## Phase 1 organization and profile API

Phase 1 adds a profile for every registered user, organization membership APIs, role information in `/api/v1/auth/me/`, and invitations. The main endpoints are:

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/profile/` | Read the signed-in user's professional profile |
| `PATCH /api/v1/profile/` | Update profile fields such as department or specialization |
| `GET /api/v1/organizations/` | List organizations where the user is a member |
| `POST /api/v1/organizations/` | Create an organization; the creator becomes its owner |
| `GET /api/v1/organizations/<id>/` | View an organization the user belongs to |
| `PATCH /api/v1/organizations/<id>/` | Owner/admin updates its name or slug |
| `DELETE /api/v1/organizations/<id>/` | Owner deletes an organization with no patient or encounter records |
| `GET /api/v1/organizations/selection/` | Read the active organization in this browser session |
| `PUT /api/v1/organizations/selection/` | Select an organization using `{ "organization_id": 123 }` |
| `DELETE /api/v1/organizations/selection/` | Clear the active organization selection |
| `GET /api/v1/organizations/<id>/members/` | List members and their roles |
| `PATCH /api/v1/organizations/<id>/members/<user_id>/` | Change a member's role |
| `DELETE /api/v1/organizations/<id>/members/<user_id>/` | Remove a member |
| `POST /api/v1/organizations/<id>/invitations/` | Owner/admin creates an invitation |
| `POST /api/v1/invitations/accept/` | The invited user accepts with the invitation token |

Invitation email delivery is intentionally not included yet. During development, the invitation endpoint returns a one-time token in its response; a later operations phase can send that token through an email provider. The invited user's email must match the invitation email before a membership is created.

Organization selection is stored in the signed-in user's session, so separate browser sessions can select different clinics. `/api/v1/auth/me/` returns the selected membership as `active_organization`. Organization access checks and the central role permission map are in `accounts/permissions.py`. Owners and admins can manage organization settings and memberships; only owners can delete an organization. Role capabilities are also enforced on the patient and encounter APIs described below.

## Phase 3 patient and encounter API

Patient and encounter data is stored in organization-owned database tables. Every request requires an active organization selected in the signed-in session. List endpoints support page-number pagination; patients also support `search` and `status` filters, while encounters support `status` and `patient_id` filters. Item lookups are scoped to the active organization and return not found for IDs outside it. The API never accepts an organization ID from the request body.

| Method and path | Purpose |
| --- | --- |
| `GET /api/v1/patients/` | List/search/filter patients in the active organization |
| `POST /api/v1/patients/` | Register a patient; MRN is generated by the server |
| `GET /api/v1/patients/<id>/` | Read a patient |
| `PUT` / `PATCH /api/v1/patients/<id>/` | Replace or update patient details |
| `DELETE /api/v1/patients/<id>/` | Delete a patient with no encounters; otherwise returns conflict |
| `GET /api/v1/encounters/` | List encounters, optionally filtered by patient or status |
| `POST /api/v1/encounters/` | Create a SOAP encounter for a patient in the active organization |
| `GET /api/v1/encounters/<id>/` | Read an encounter |
| `PUT` / `PATCH /api/v1/encounters/<id>/` | Replace or update an encounter |
| `DELETE /api/v1/encounters/<id>/` | Delete an encounter |

Owners, admins, and doctors can create and manage patient and encounter records; all organization members can read them. Primary and assigned doctors must be doctor members of the active organization. The dashboard now loads and creates patient and encounter records through these APIs; its patient and encounter sample data has been removed.

## Phase 4 database protection

On PostgreSQL, migration `0004_encrypt_clinical_fields_and_rls` encrypts patient date of birth and phone, plus encounter chief complaint, vitals, objective notes, assessment, and plan using Fernet. The migration encrypts existing rows as well as future writes. Names and medical record numbers stay searchable. Server-side patient search therefore matches names and MRN; phone search is not performed in SQL. RLS policies independently restrict patient and encounter rows to the signed-in user’s active organization. SQLite remains available for local development but does not enforce PostgreSQL RLS.

Set a stable, dedicated `FIELD_ENCRYPTION_KEY` before deploying or storing data you need to retain. Generate one with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this key in a secrets manager and in a separately protected backup. Losing or changing it makes encrypted fields unreadable. In development only, when the key is omitted, the app derives one from `DJANGO_SECRET_KEY`; this is intended for local use and must not be used for retained production data. Run `python manage.py migrate` against PostgreSQL to encrypt existing rows and enable the policies. The app database role must remain a non-superuser without `BYPASSRLS`; PostgreSQL superusers and bypass roles can ignore row policies.

## Phase 5 audit log

Migration `0005_auditevent` creates a per-organization, append-only audit chain. Successful patient and encounter collection reads, individual reads, creates, updates, and deletes are recorded with actor and resource IDs. Audit metadata does not include patient names, phone numbers, or clinical field values. Owners and admins can verify the active clinic's chain with `GET /api/v1/audit/verify/`; a valid chain returns HTTP 200, and detected corruption returns HTTP 409 with the first invalid sequence. Other roles cannot run verification. PostgreSQL adds row-level tenant policies and triggers that reject updates, deletes, and truncation; application model/queryset guards provide the same append-only behavior in local SQLite. The hashes make changes detectable, but this database-local chain is not an external backup or cryptographic signature.

## Planned milestones

1. Account and organization foundation, registration, organization management, and session login. (Complete; JWT remains deferred unless a stateless client is needed.)
2. Central RBAC permission map and organization access enforcement. (Complete for current organization and membership APIs; patient and encounter enforcement follows their implementation.)
3. Patient and encounter CRUD with tenant scoping and IDOR protection. (Complete for the API and dashboard read/create flows.)
4. PostgreSQL row-level security and application-level field encryption. (Implemented; PostgreSQL runtime verification is pending.)
5. Append-only, hash-chained audit log and verification endpoint. (Implemented; apply migration `0005_auditevent` before use.)
6. Usage metering, plan limits, and rate limiting.
7. Cross-tenant attack suite, load testing, and documented benchmarks.

Success metrics will be reported only after they are measured: tenant-isolation test count, audit tamper checks, and patient-list latency under a documented workload.
