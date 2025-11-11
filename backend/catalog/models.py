from __future__ import annotations
from django.db import models


class Product(models.Model):
    """Global product identity (not tied to any single store).

    Keep bilingual names; optionally a brand and variant string (e.g., "3% 1 litre").
    Products can be sold in many stores via the through table StoreProduct.
    """
    name_he = models.CharField(max_length=160)
    name_en = models.CharField(max_length=160, blank=True)
    brand = models.CharField(max_length=120, blank=True)
    variant = models.CharField(max_length=160, blank=True)
    default_unit_type = models.CharField(
        max_length=30,
        blank=True,
        help_text="e.g., liter, kilogram, unit",
    )
    default_unit_quantity = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="e.g., 1.50 (liters) or 2.00 (kg)",
    )
    category = models.CharField(max_length=120, blank=True)
    barcode = models.CharField(max_length=32, blank=True, null=True, unique=True)
    is_active = models.BooleanField(default=True)

    # Many-to-many to stores through StoreProduct mapping table
    stores = models.ManyToManyField(
        "stores.Store",
        through="StoreProduct",
        related_name="products",
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["name_he"], name="product_name_he_idx"),
            models.Index(fields=["name_en"], name="product_name_en_idx"),
            models.Index(fields=["brand", "category"], name="product_brand_cat_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.name_he or self.name_en

    def save(self, *args, **kwargs):
        if not self.name_en:
            self.name_en = self.name_he
        if not self.name_he:
            self.name_he = self.name_en
        super().save(*args, **kwargs)


class StoreProduct(models.Model):
    """Through model for Product×Store availability/metadata.
    Useful for store-specific SKU codes and quick existence queries.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE)
    sku = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("product", "store")]
        indexes = [
            models.Index(fields=["store", "product"], name="storeproduct_store_product_idx"),
            models.Index(fields=["product", "store"], name="storeproduct_product_store_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.product_id} @ {self.store_id}"
