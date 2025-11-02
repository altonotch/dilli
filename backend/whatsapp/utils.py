from __future__ import annotations
import hashlib
import re
import logging
import json
from urllib import request, error
from django.conf import settings


logger = logging.getLogger(__name__)

_NON_DIGIT = re.compile(r"\D+")
_HEBREW_CHARS = re.compile(r"[\u0590-\u05FF]")


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


def detect_locale(text: str) -> str:
    """Very simple detector: Hebrew characters => he-IL else en-US."""
    try:
        return 'he-IL' if _HEBREW_CHARS.search(text or '') else 'en-US'
    except Exception:
        return 'en-US'


def get_intro_message(locale: str) -> str:
    if (locale or '').lower().startswith('he'):
        return (
            """ברוך/ה הבא/ה ל"דיללי" — דילים מהסופר לידך.
מה תרצה/י לעשות?
1) למצוא דיל
2) להוסיף דיל
3) איך זה עובד"""
        )
    return (
        """Welcome to "Dilli" — deals from the supermarket near you.
What would you like to do?
1) Find a deal
2) Add a deal
3) How it works"""
    )


def send_whatsapp_text(to_e164: str, body: str) -> bool:
    """Send a text message via WhatsApp Cloud API.

    Returns True on 2xx success, False otherwise.
    """
    token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')
    phone_id = getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
    if not token or not phone_id:
        logger.warning("WhatsApp credentials not configured; skipping send")
        return False

    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_e164,
        "type": "text",
        "text": {"body": body, "preview_url": False},
    }
    data = json.dumps(payload).encode('utf-8')
    req = request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            # Any 2xx is success
            return 200 <= resp.status < 300
    except error.HTTPError as e:
        logger.error("WhatsApp send failed: %s %s", e.code, getattr(e, 'reason', ''))
    except Exception:
        logger.exception("WhatsApp send failed unexpectedly")
    return False
