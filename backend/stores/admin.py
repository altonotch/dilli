from __future__ import annotations
from django.contrib import admin, messages
from django.contrib.gis import admin as gis_admin
from django.contrib.gis.geos import Point
from django.utils.translation import gettext_lazy as _

from .geoapify import geocode_store_name, GeoapifyError
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
    actions = ["geocode_with_geoapify"]

    @admin.action(description=_("Geocode selected stores via Geoapify"))
    def geocode_with_geoapify(self, request, queryset):
        successes = 0
        for store in queryset:
            query_name = store.display_name or store.name
            try:
                result = geocode_store_name(query_name, store.city)
            except GeoapifyError as exc:
                messages.error(request, _("Geoapify error for %(store)s: %(error)s") % {"store": store, "error": exc})
                continue
            if not result:
                messages.warning(request, _("No result found for %(store)s") % {"store": store})
                continue
            store.location = result.point
            if not store.address:
                store.address = result.formatted
            if result.city and not store.city:
                store.city = result.city
            store.save(update_fields=["location", "address", "city", "updated_at"])
            successes += 1
        if successes:
            messages.success(request, _("Updated %(count)s store(s) with Geoapify results.") % {"count": successes})
