from __future__ import annotations
from django.contrib import admin
from django.contrib.gis import admin as gis_admin
from .models import StoreChain, Store


@admin.register(StoreChain)
class StoreChainAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(Store)
class StoreAdmin(gis_admin.GISModelAdmin):
    list_display = ("__str__", "chain", "city", "is_active")
    list_filter = ("chain", "city", "is_active")
    search_fields = ("name", "display_name", "city", "address")
    readonly_fields = ("created_at", "updated_at")
    # You can tune map defaults later
    default_zoom = 12
