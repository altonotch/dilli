from __future__ import annotations
from django import forms
from django.contrib import admin
from django.contrib.gis import admin as gis_admin
from django.contrib.gis.geos import Point

from .models import StoreChain, Store


@admin.register(StoreChain)
class StoreChainAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


class StoreAdminForm(forms.ModelForm):
    coordinate = forms.CharField(
        required=False,
        help_text="Paste Google Maps lat,lng (e.g., 32.10584, 34.94315). Overrides fields below.",
    )
    latitude = forms.FloatField(required=False, help_text="Latitude (e.g., 32.09556)")
    longitude = forms.FloatField(required=False, help_text="Longitude (e.g., 34.95664)")

    class Meta:
        model = Store
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.location:
            self.fields["latitude"].initial = self.instance.location.y
            self.fields["longitude"].initial = self.instance.location.x

    def save(self, commit=True):
        instance = super().save(commit=False)
        coord = (self.cleaned_data.get("coordinate") or "").strip()
        lat = self.cleaned_data.get("latitude")
        lon = self.cleaned_data.get("longitude")
        if coord:
            try:
                parts = [p.strip() for p in coord.split(",")]
                if len(parts) == 2:
                    lat = float(parts[0])
                    lon = float(parts[1])
            except ValueError:
                pass
        if lat is not None and lon is not None:
            instance.location = Point(lon, lat, srid=4326)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(Store)
class StoreAdmin(gis_admin.GISModelAdmin):
    form = StoreAdminForm
    list_display = ("__str__", "chain", "city", "is_active")
    list_filter = ("chain", "city", "is_active")
    search_fields = ("name", "display_name", "city", "address")
    readonly_fields = ("created_at", "updated_at")
    # You can tune map defaults later
    default_zoom = 12
