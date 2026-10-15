from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.conf import settings
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def index(request):
    """Renders the main ClinicOS single-page dashboard UI."""
    if not request.user.is_authenticated and not (settings.DEBUG and request.GET.get("demo") == "1"):
        return redirect("login")
    return render(request, "index.html", {"demo_enabled": settings.DEBUG})


@ensure_csrf_cookie
def login_view(request):
    """Renders the ClinicOS authentication portal (Sign In / Create Account)."""
    if request.user.is_authenticated and request.GET.get("accept_invite") != "1":
        return redirect("index")
    return render(request, "login.html", {"demo_enabled": settings.DEBUG})


def readiness(request):
    """Minimal platform readiness probe; never returns database details."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})

