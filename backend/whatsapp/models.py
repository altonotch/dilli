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

    # Profile (optional)
    display_name = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, default='he-IL')
    city = models.CharField(max_length=120, blank=True)
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
