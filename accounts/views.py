from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def index(request):
    """Renders the main ClinicOS single-page dashboard UI."""
    if not request.user.is_authenticated and request.GET.get("demo") != "1":
        return redirect("login")
    return render(request, "index.html")


@ensure_csrf_cookie
def login_view(request):
    """Renders the ClinicOS authentication portal (Sign In / Create Account)."""
    if request.user.is_authenticated:
        return redirect("index")
    return render(request, "login.html")


def readiness(request):
    """Return a minimal readiness result without exposing database details."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})

