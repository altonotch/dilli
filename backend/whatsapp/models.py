from __future__ import annotations
import uuid
from django.db import models


class WAUser(models.Model):
    """Minimal user identified by WhatsApp sender hash.

    No passwords; identity is wa_id_hash (SHA-256 of wa_id + WA_SALT).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity
    wa_id_hash = models.CharField(max_length=64, unique=True)
    wa_last4 = models.CharField(max_length=4, blank=True, null=True, help_text="Support-only lookup; do not store full number")
    wa_number = models.CharField(max_length=32, blank=True, help_text="Digits-only WhatsApp ID (E.164); used for proactive notifications.")

    # Profile (optional)
    display_name = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, default='he-IL')
    city = models.CharField(max_length=120, blank=True)
    city_obj = models.ForeignKey(
        "stores.City",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wa_users",
    )
    tz = models.CharField(max_length=64, default='Asia/Jerusalem')

    # Lifecycle
    consent_ts = models.DateTimeField(blank=True, null=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(blank=True, null=True, db_index=True)

    # Roles
    class Roles(models.TextChoices):
        USER = 'user', 'User'
        MODERATOR = 'moderator', 'Moderator'
        ADMIN = 'admin', 'Admin'

    role = models.CharField(max_length=10, choices=Roles.choices, default=Roles.USER)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['last_seen']),
        ]
        verbose_name = 'WA User'
        verbose_name_plural = 'WA Users'

    def __str__(self) -> str:  # pragma: no cover
        return f"WAUser({self.id})"


class DealReportSession(models.Model):
    """Tracks a multi-step WhatsApp flow where the user shares a new deal."""

    class Steps(models.TextChoices):
        STORE = "store", "store"
        BRANCH = "branch", "branch"
        CITY = "city", "city"
        STORE_CONFIRM = "store_confirm", "store_confirm"
        PRODUCT = "product", "product"
        BRAND = "brand", "brand"
        UNIT_CATEGORY = "unit_category", "unit_category"
        UNIT_TYPE = "unit_type", "unit_type"
        UNIT_QUANTITY = "unit_quantity", "unit_quantity"
        PRICE = "price", "price"
        UNITS = "units", "units"
        CLUB = "club", "club"
        LIMIT = "limit", "limit"
        CART = "cart", "cart"
        COMPLETE = "complete", "complete"
        CANCELED = "canceled", "canceled"

    user = models.ForeignKey(WAUser, on_delete=models.CASCADE, related_name="deal_sessions")
    step = models.CharField(max_length=20, choices=Steps.choices, default=Steps.CITY)
    data = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["updated_at"]),
        ]
        ordering = ["-updated_at"]

    def reset(self) -> None:
        self.step = self.Steps.CITY
        self.data = {}
        self.is_active = True


class DealLookupSession(models.Model):
    """Tracks a guided flow where the user searches for deals."""

    class Steps(models.TextChoices):
        PRODUCT = "product", "product"
        BRAND = "brand", "brand"
        LOCATION = "location", "location"
        COMPLETE = "complete", "complete"
        CANCELED = "canceled", "canceled"

    user = models.ForeignKey(WAUser, on_delete=models.CASCADE, related_name="deal_lookup_sessions")
    step = models.CharField(max_length=20, choices=Steps.choices, default=Steps.PRODUCT)
    data = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["updated_at"]),
        ]
        ordering = ["-updated_at"]

    def reset(self) -> None:
        self.step = self.Steps.PRODUCT
        self.data = {}
        self.is_active = True
