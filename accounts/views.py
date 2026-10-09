from django.shortcuts import render


def index(request):
    """Renders the main ClinicOS single-page dashboard UI."""
    return render(request, "index.html")
