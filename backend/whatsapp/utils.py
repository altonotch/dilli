from __future__ import annotations
import hashlib
import re
import uuid
from dataclasses import dataclass
from django.conf import settings


_NON_DIGIT = re.compile(r"\D+")


def normalize_wa_id(raw: str) -> str:
    """Normalize WhatsApp E.164 sender id string to digits-only."""
    return _NON_DIGIT.sub("", raw or "").lstrip("0")


def compute_wa_hash(wa_id: str) -> str:
    wa_salt = getattr(settings, 'WA_SALT', '')
    if not wa_salt:
        # Fail closed if salt is not configured
        raise RuntimeError('WA_SALT is not configured')
    h = hashlib.sha256()
    h.update((wa_id + wa_salt).encode('utf-8'))
    return h.hexdigest()
