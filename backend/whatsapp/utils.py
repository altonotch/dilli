from __future__ import annotations
import hashlib
import re
import logging
import json
from urllib import request, error
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _


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


def normalize_locale(locale: str) -> str:
    """Normalize locale code to either 'he' or 'en'. Defaults to 'en' if unknown."""
    s = (locale or "").strip().lower()
    if s.startswith("he") or s in ("hebrew", "עברית"):
        return "he"
    return "en"


def detect_locale(text: str) -> str:
    """Heuristic: Hebrew characters => 'he', else 'en'."""
    try:
        return 'he' if _HEBREW_CHARS.search(text or '') else 'en'
    except Exception:
        return 'en'


def parse_language_choice(text: str) -> str | None:
    """Parse explicit language choice from user text.

    Accepts digits (1/2), language names (English/עברית), and short codes (he/en).
    Returns 'he', 'en', or None if no explicit choice detected.
    """
    t = (text or "").strip().lower()
    if not t:
        return None

    # Normalize common tokens; allow matching even if surrounded by other text
    if "עברית" in t or re.search(r"\bhe\b", t) or t == "1":
        return "he"
    if "english" in t or re.search(r"\ben\b", t) or t == "2":
        return "en"
    return None


def get_language_prompt() -> str:
    """Bilingual language selection message shown on first contact."""
    return (
        "Please choose your language / נא לבחור שפה\n"
        "1) עברית\n"
        "2) English"
    )


def get_intro_message(locale: str) -> str:
    loc = normalize_locale(locale)
    with translation.override(loc):
        msg1 = _(
            "🛒 Dilli — save together on groceries.\n"
            "Send prices you see in the supermarket and help everyone find cheaper options.\n\n"
            "👉 To share a deal: write product name, price, and store.\n"
            "Example:\n"
            "Milk 3% 4.20 Shufersal Ayalon"
        )
        msg2 = _(
            "You can also:\n"
            "• \"Find milk 3%\" — see nearby prices\n"
            "• Send your 📍 location — to improve results\n"
            "• Send 👍 or 👎 on a deal you saw\n\n"
            "Type \"help\" anytime to see this again."
        )
    return "\n\n".join([msg1, msg2])


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
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
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
