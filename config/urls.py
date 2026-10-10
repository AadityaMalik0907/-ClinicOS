"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""

from django.contrib import admin
from django.urls import path
from accounts.views import index
from accounts.api_views import (
    CurrentUserView,
    LoginView,
    LogoutView,
    RegisterView,
    csrf_cookie,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", index, name="index"),
    path("api/auth/csrf/", csrf_cookie, name="auth-csrf"),
    path("api/auth/register/", RegisterView.as_view(), name="auth-register"),
    path("api/auth/login/", LoginView.as_view(), name="auth-login"),
    path("api/auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("api/auth/me/", CurrentUserView.as_view(), name="auth-me"),
]
