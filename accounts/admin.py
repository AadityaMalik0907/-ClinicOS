from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Encounter, Membership, Organization, OrganizationInvitation, Patient, User, UserProfile


@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff")
    fieldsets = ((None, {"fields": ("email", "password")}), ("Personal info", {"fields": ("first_name", "last_name")}), ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}))
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    search_fields = ("email",)
    filter_horizontal = ("groups", "user_permissions")


admin.site.register(Organization)
admin.site.register(Membership)
admin.site.register(UserProfile)
admin.site.register(OrganizationInvitation)
admin.site.register(Patient)
admin.site.register(Encounter)
