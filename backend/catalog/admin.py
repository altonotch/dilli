from __future__ import annotations
from django.contrib import admin
from .models import Product, StoreProduct


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name_he", "name_en", "brand", "category", "is_active")
    list_filter = ("is_active", "brand", "category")
    search_fields = ("name_he", "name_en", "brand", "variant", "category")


@admin.register(StoreProduct)
class StoreProductAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "store", "sku", "active", "first_seen", "last_seen")
    list_filter = ("active",)
    search_fields = ("sku",)
    autocomplete_fields = ("product", "store")
    readonly_fields = ("first_seen", "last_seen")
