from __future__ import annotations
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.utils.text import slugify


def _contains_hebrew(value: str) -> bool:
    return any("\u0590" <= ch <= "\u05FF" for ch in value or "")


def _contains_latin(value: str) -> bool:
    return any(
        ("a" <= ch <= "z") or ("A" <= ch <= "Z")
        for ch in value or ""
    )


class City(models.Model):
    """Canonical city with bilingual names."""
    name_he = models.CharField(max_length=120, blank=True)
    name_en = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "City"
        verbose_name_plural = "Cities"
        indexes = [
            models.Index(fields=["name_he"], name="stores_city_name_he_idx"),
            models.Index(fields=["name_en"], name="stores_city_name_en_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.name_en or self.name_he or self.slug

    def save(self, *args, **kwargs):
        if not self.name_he and self.name_en:
            self.name_he = self.name_en
        if not self.name_en and self.name_he:
            self.name_en = self.name_he
        if not self.slug:
            base_slug_source = self.name_en or self.name_he or "city"
            base_slug = slugify(base_slug_source, allow_unicode=True) or "city"
            slug_candidate = base_slug
            counter = 1
            while City.objects.exclude(pk=self.pk).filter(slug=slug_candidate).exists():
                counter += 1
                slug_candidate = f"{base_slug}-{counter}"
            self.slug = slug_candidate
        super().save(*args, **kwargs)


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
    city_he = models.CharField(max_length=120, blank=True)
    city_en = models.CharField(max_length=120, blank=True)
    city_obj = models.ForeignKey(
        City,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stores",
    )

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
        city_value = self.city_obj.display_name if self.city_obj else (self.city or self.city_en or self.city_he)
        city = f", {city_value}" if city_value else ""
        return f"{prefix}{self.name}{city}"

    def save(self, *args, **kwargs):
        if not self.name_he and self.name:
            self.name_he = self.name
        if not self.name_en and self.name:
            self.name_en = self.name
        if not self.name:
            self.name = self.name_en or self.name_he or ""

        base_city = self.city or ""
        if base_city:
            if not self.city_he and _contains_hebrew(base_city):
                self.city_he = base_city
            if not self.city_en and _contains_latin(base_city):
                self.city_en = base_city

        if self.city_obj:
            if not self.city_he:
                self.city_he = self.city_obj.name_he
            if not self.city_en:
                self.city_en = self.city_obj.name_en
            if not self.city:
                self.city = self.city_obj.display_name

        if not self.city and (self.city_en or self.city_he):
            self.city = self.city_en or self.city_he

        super().save(*args, **kwargs)
