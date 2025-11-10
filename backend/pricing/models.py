from __future__ import annotations
from django.db import models

PRICE_DECIMAL_PLACES = 2
PRICE_MAX_DIGITS = 7  # up to 99999.99


class PriceReport(models.Model):
    """User-submitted observation: product at a store at a price and time.
    Keep immutable for audit/debug; currency is implicit (local).
    """

    user = models.ForeignKey("whatsapp.WAUser", on_delete=models.SET_NULL, null=True, blank=True)
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT)

    price = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)
    units_in_price = models.PositiveSmallIntegerField(
        default=1,
        help_text="Number of units covered by the reported price (e.g., 3 for a 3-pack deal).",
    )
    is_for_club_members_only = models.BooleanField(
        default=False,
        help_text="Whether the deal is restricted to loyalty/club members.",
    )
    min_cart_total = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        null=True,
        blank=True,
        help_text="Minimum cart total required to redeem the deal (e.g., 100 for orders over 100₪).",
    )
    deal_notes = models.CharField(
        max_length=240,
        blank=True,
        help_text="Free-text qualifier for other deal conditions (e.g., loyalty-only, coupons).",
    )
    needs_moderation = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True until a moderator validates the report.",
    )
    observed_at = models.DateTimeField(db_index=True)

    # Optional extras
    product_text_raw = models.CharField(max_length=240, blank=True)
    wa_message_id = models.CharField(max_length=128, blank=True)
    locale = models.CharField(max_length=10, blank=True)
    source = models.CharField(max_length=40, default="whatsapp")
    receipt_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["product", "store", "observed_at"], name="pr_product_store_time_idx"),
            models.Index(fields=["store", "observed_at"], name="pr_store_time_idx"),
            models.Index(fields=["product", "observed_at"], name="pr_product_time_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"PriceReport(product={self.product_id}, store={self.store_id}, price={self.price})"


class StoreProductSnapshot(models.Model):
    """Latest known price per product×store (denormalized cache)."""

    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    store = models.ForeignKey("stores.Store", on_delete=models.CASCADE)
    last_price = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)
    last_observed_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("product", "store")]
        indexes = [
            models.Index(fields=["store", "product"], name="sps_store_product_idx"),
            models.Index(fields=["product", "store"], name="sps_product_store_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Snapshot(product={self.product_id}, store={self.store_id}, price={self.last_price})"
