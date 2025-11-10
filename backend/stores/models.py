from __future__ import annotations
from django.contrib.gis.db import models as gis_models
from django.db import models


class StoreChain(models.Model):
    """Optional chain/brand for stores. Local makolet stores can have chain=None."""
    name = models.CharField(max_length=120, unique=True)
    name_he = models.CharField(max_length=120, blank=True)
    name_en = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=140, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Store Chain"
        verbose_name_plural = "Store Chains"

    def __str__(self) -> str:  # pragma: no cover
        return self.name or self.name_en or self.name_he or str(self.pk)

    def save(self, *args, **kwargs):
        if not self.name_he and self.name:
            self.name_he = self.name
        if not self.name_en and self.name:
            self.name_en = self.name
        if not self.name:
            self.name = self.name_en or self.name_he or ""
        super().save(*args, **kwargs)


class Store(models.Model):
    """A physical store (branch or standalone location)."""
    chain = models.ForeignKey(
        StoreChain,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stores",
    )
    # Human name for the branch/store (e.g., "Givat Tal" or the store's full name)
    name = models.CharField(max_length=160)
    name_he = models.CharField(max_length=160, blank=True)
    name_en = models.CharField(max_length=160, blank=True)
    display_name = models.CharField(max_length=200, blank=True)

    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)

    # GeoDjango point (WGS84). geography=True gives great-circle distance support.
    location = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)

    # Optional external ids for place services, etc.
    external_ids = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Store"
        verbose_name_plural = "Stores"
        indexes = [
            models.Index(fields=["city", "name"], name="store_city_name_idx"),
            models.Index(fields=["chain", "city"], name="store_chain_city_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        prefix = f"{self.chain.name} " if self.chain else ""
        city = f", {self.city}" if self.city else ""
        return f"{prefix}{self.name}{city}"

    def save(self, *args, **kwargs):
        if not self.name_he and self.name:
            self.name_he = self.name
        if not self.name_en and self.name:
            self.name_en = self.name
        if not self.name:
            self.name = self.name_en or self.name_he or ""
        super().save(*args, **kwargs)
