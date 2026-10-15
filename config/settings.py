"""Environment-driven settings for local development and hosted deployments."""
"""Environment-driven settings for local development and hosted deployments."""

import base64
import hashlib
import os
import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit
from cryptography.fernet import Fernet
from django.http.request import validate_host
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG", True)
EXPOSE_INVITATION_TOKENS = env_bool("DEVELOPMENT_INVITATION_TOKENS", DEBUG)
if not DEBUG and EXPOSE_INVITATION_TOKENS:
    raise ImproperlyConfigured("DEVELOPMENT_INVITATION_TOKENS cannot be enabled when DEBUG is false.")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me" if DEBUG else "")
if not SECRET_KEY or SECRET_KEY == "dev-only-change-me":
    if not DEBUG:
        raise ImproperlyConfigured("Set a unique DJANGO_SECRET_KEY for deployments with DEBUG disabled.")

_field_key = os.environ.get("FIELD_ENCRYPTION_KEY")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def env_int(name, default, *, minimum=0):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer.") from None
    if value < minimum:
        raise ImproperlyConfigured(f"{name} must be at least {minimum}.")
    return value


def csv_values(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_hostname(value):
    """Validate one explicit hostname (never accept URL paths or ports)."""
    hostname = value.strip().lower().rstrip(".")
    domain = hostname[1:] if hostname.startswith(".") else hostname
    if (
        not domain
        or "://" in hostname
        or "/" in hostname
        or "@" in hostname
        or re.search(r"\s", hostname)
        or not validate_host(domain, [domain])
    ):
        raise ImproperlyConfigured("Host settings must contain hostnames only, without schemes, paths, or ports.")
    return hostname


def normalize_origin(value, *, debug):
    """Validate a complete trusted origin; HTTP is limited to local development."""
    raw = value.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise ImproperlyConfigured("CSRF trusted origins must be valid absolute origins.") from None
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and (not debug or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}))
    ):
        raise ImproperlyConfigured("CSRF trusted origins must be complete HTTPS origins (or local HTTP origins in development).")
    try:
        parsed.port
    except ValueError:
        raise ImproperlyConfigured("CSRF trusted origin contains an invalid port.") from None
    if parsed.hostname != "::1":
        normalize_hostname(parsed.hostname)
    return raw


DEBUG = env_bool("DJANGO_DEBUG", False)
if os.environ.get("VERCEL_ENV", "").strip().lower() == "production":
    DEBUG = False
EXPOSE_INVITATION_TOKENS = env_bool("DEVELOPMENT_INVITATION_TOKENS", DEBUG)
if not DEBUG and EXPOSE_INVITATION_TOKENS:
    raise ImproperlyConfigured("DEVELOPMENT_INVITATION_TOKENS cannot be enabled when DEBUG is false.")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me" if DEBUG else "").strip()
if not SECRET_KEY or SECRET_KEY == "dev-only-change-me":
    if not DEBUG:
        raise ImproperlyConfigured("Set a unique DJANGO_SECRET_KEY for deployments with DEBUG disabled.")

_field_key = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
if not _field_key:
    if not DEBUG:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is required when DEBUG is false.")
    _field_key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()).decode("ascii")
FIELD_ENCRYPTION_KEY = _field_key
try:
    Fernet(FIELD_ENCRYPTION_KEY.encode("ascii"))
except (ValueError, UnicodeEncodeError):
    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be a valid Fernet key.") from None
_default_hosts = "localhost,127.0.0.1" if DEBUG else os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", _default_hosts).split(",") if h.strip()]
vercel_hostname = "clinic-os-flax.vercel.app"
if vercel_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(vercel_hostname)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS or use a supported platform hostname variable.")
render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)
if "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")
try:
    Fernet(FIELD_ENCRYPTION_KEY.encode("ascii"))
except (ValueError, UnicodeEncodeError):
    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be a valid Fernet key.") from None

VERCEL_HOSTNAME = "clinic-os-flax.vercel.app"
_host_values = [VERCEL_HOSTNAME]
_host_values.extend(csv_values(os.environ.get("DJANGO_ALLOWED_HOSTS", "")))
for _vercel_key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _vercel_host = os.environ.get(_vercel_key, "").strip()
    if _vercel_host:
        _host_values.append(_vercel_host)
if DEBUG:
    _host_values.extend(("localhost", "127.0.0.1"))
ALLOWED_HOSTS = list(dict.fromkeys(normalize_hostname(host) for host in _host_values))
ALLOWED_HOSTS.append("testserver")

SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
CSRF_TRUSTED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if SITE_URL and SITE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(SITE_URL)
vercel_origin = f"https://{vercel_hostname}"
if vercel_origin not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(vercel_origin)
if render_hostname:
    render_origin = f"https://{render_hostname}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "86400" if not DEBUG else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if env_bool("DJANGO_TRUST_PROXY_SSL", not DEBUG):
    # Only enable this behind a trusted reverse proxy that overwrites this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")
_origin_values = csv_values(os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", ""))
if SITE_URL:
    _origin_values.append(SITE_URL)
_origin_values.append(f"https://{VERCEL_HOSTNAME}")
for _vercel_key in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
    _vercel_host = os.environ.get(_vercel_key, "").strip()
    if _vercel_host:
        _origin_values.append(f"https://{_vercel_host}")
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(
    normalize_origin(origin, debug=DEBUG) for origin in _origin_values
))

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", "86400" if not DEBUG else "0")
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if env_bool("DJANGO_TRUST_PROXY_SSL", not DEBUG):
    # Vercel terminates HTTPS and sets this header on requests to the function.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
]

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "accounts.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("API_ANON_RATE", "120/hour"),
        "user": os.environ.get("API_USER_RATE", "1000/hour"),
        "auth_login": os.environ.get("API_LOGIN_RATE", "10/minute"),
        "auth_register": os.environ.get("API_REGISTER_RATE", "5/hour"),
    },
}

if DEBUG:
    CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "clinicos-api-throttles",
    }}
else:
    # Shared among web workers; create the table with `manage.py createcachetable`.
    CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": os.environ.get("DJANGO_CACHE_TABLE", "clinicos_cache"),
        "TIMEOUT": 300,
    }}

FREE_PATIENT_LIMIT = int(os.environ.get("FREE_PATIENT_LIMIT", "100"))
FREE_ENCOUNTERS_MONTHLY_LIMIT = int(os.environ.get("FREE_ENCOUNTERS_MONTHLY_LIMIT", "250"))

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.PostgresRLSContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    parsed_database_url = urlsplit(DATABASE_URL)
    if parsed_database_url.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ImproperlyConfigured("DATABASE_URL must use PostgreSQL.")
    database_options = dict(parse_qsl(parsed_database_url.query))
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed_database_url.path.lstrip("/")),
        "USER": unquote(parsed_database_url.username or ""),
        "PASSWORD": unquote(parsed_database_url.password or ""),
        "HOST": parsed_database_url.hostname or "",
        "PORT": str(parsed_database_url.port or 5432),
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": database_options,
    }}
elif os.environ.get("DB_ENGINE", "sqlite").lower() == "postgres":
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_connection_age = env_int("DB_CONN_MAX_AGE", 0)
if DATABASE_URL:
    try:
        parsed_database_url = urlsplit(DATABASE_URL)
    except ValueError:
        raise ImproperlyConfigured("DATABASE_URL is not a valid PostgreSQL URL.") from None
    if parsed_database_url.scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
        raise ImproperlyConfigured("DATABASE_URL must use PostgreSQL.")
    try:
        _database_hostname = parsed_database_url.hostname
        _database_port = parsed_database_url.port
    except ValueError:
        raise ImproperlyConfigured("DATABASE_URL contains an invalid host or port.") from None
    if not _database_hostname or not parsed_database_url.path.strip("/"):
        raise ImproperlyConfigured("DATABASE_URL must include a PostgreSQL host and database name.")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed_database_url.path.lstrip("/")),
        "USER": unquote(parsed_database_url.username or ""),
        "PASSWORD": unquote(parsed_database_url.password or ""),
        "HOST": _database_hostname,
        "PORT": str(_database_port or 5432),
        "CONN_MAX_AGE": _connection_age,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": dict(parse_qsl(parsed_database_url.query)),
    }}
elif DEBUG and os.environ.get("DB_ENGINE", "sqlite").lower() == "postgres":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "clinicos"),
        "USER": os.environ.get("POSTGRES_APP_USER", os.environ.get("POSTGRES_USER", "clinicos")),
        "PASSWORD": os.environ.get("POSTGRES_APP_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "clinicos-dev")),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
    }}
elif DEBUG:
elif DEBUG:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    raise ImproperlyConfigured("Set DATABASE_URL for a persistent PostgreSQL database in production.")
else:
    raise ImproperlyConfigured("Set DATABASE_URL to a persistent PostgreSQL database for production.")

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not DEBUG)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "ClinicOS <no-reply@localhost>")
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
