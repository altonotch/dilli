from django.contrib import admin
from .models import WAUser, DealReportSession


@admin.register(WAUser)
class WAUserAdmin(admin.ModelAdmin):
    list_display = ("id", "role", "is_active", "last_seen", "date_joined")
    list_filter = ("role", "is_active")
    search_fields = ("id", "wa_last4")
    readonly_fields = ("wa_id_hash", "date_joined", "last_seen", "consent_ts")


@admin.register(DealReportSession)
class DealReportSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "step", "is_active", "updated_at")
    list_filter = ("is_active", "step")
    search_fields = ("user__display_name", "user__wa_last4")
    readonly_fields = ("created_at", "updated_at", "data")
