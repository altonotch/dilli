from django.contrib import admin
from .models import WAUser


@admin.register(WAUser)
class WAUserAdmin(admin.ModelAdmin):
    list_display = ("id", "role", "is_active", "last_seen", "date_joined")
    list_filter = ("role", "is_active")
    search_fields = ("id", "wa_last4")
    readonly_fields = ("wa_id_hash", "date_joined", "last_seen", "consent_ts")
