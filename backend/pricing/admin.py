from __future__ import annotations
from django.contrib import admin
from .models import PriceReport, StoreProductSnapshot


@admin.register(PriceReport)
class PriceReportAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "store", "price", "observed_at", "user", "source")
    list_filter = ("source", "observed_at")
    search_fields = ("product__name_he", "product__name_en", "store__name", "store__city")
    autocomplete_fields = ("product", "store", "user")
    readonly_fields = ("created_at",)
    date_hierarchy = "observed_at"


@admin.register(StoreProductSnapshot)
class StoreProductSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "store", "last_price", "last_observed_at", "updated_at")
    search_fields = ("product__name_he", "product__name_en", "store__name", "store__city")
    list_filter = ("last_observed_at",)
    autocomplete_fields = ("product", "store")
