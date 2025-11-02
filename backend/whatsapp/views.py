from __future__ import annotations
import hmac
import json
import logging
from hashlib import sha256

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework import status

from .models import WAUser
from .utils import normalize_wa_id, compute_wa_hash, detect_locale, get_intro_message, send_whatsapp_text
from .throttling import IPRateThrottle, WaHashRateThrottle

logger = logging.getLogger(__name__)


def _verify_signature(request: HttpRequest) -> bool:
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature or not settings.META_APP_SECRET:
        return False
    if not signature.startswith("sha256="):
        return False
    provided = signature.split("=", 1)[1].strip()
    mac = hmac.new(settings.META_APP_SECRET.encode("utf-8"), msg=request.body, digestmod=sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(provided, expected)


@method_decorator(csrf_exempt, name="dispatch")
class MetaWebhookView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes = [IPRateThrottle, WaHashRateThrottle]

    def get(self, request: HttpRequest) -> HttpResponse:
        # Verification handshake
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        if mode == "subscribe" and token and token == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponse(status=status.HTTP_403_FORBIDDEN)

    def post(self, request: HttpRequest) -> JsonResponse:
        if not _verify_signature(request):
            return JsonResponse({"detail": "invalid signature"}, status=status.HTTP_403_FORBIDDEN)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"detail": "bad json"}, status=status.HTTP_400_BAD_REQUEST)

        processed: int = 0
        # WhatsApp webhook structure: entry -> changes -> value -> messages[]
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", []) or []
                contacts = {c.get("wa_id"): c for c in value.get("contacts", [])}
                for msg in messages:
                    wa_raw = str(msg.get("from", ""))
                    wa_norm = normalize_wa_id(wa_raw)
                    if not wa_norm:
                        continue
                    wa_hash = compute_wa_hash(wa_norm)

                    defaults = {
                        "consent_ts": timezone.now(),
                        "role": WAUser.Roles.USER,
                    }
                    # Optional locale detection from first text message body
                    try:
                        body_text = (msg.get("text") or {}).get("body") if isinstance(msg.get("text"), dict) else ""
                    except Exception:
                        body_text = ""
                    defaults["locale"] = detect_locale(body_text or "")

                    # Optional display name
                    contact = contacts.get(wa_norm) or (value.get("contacts", [{}])[0] if value.get("contacts") else {})
                    display_name = (contact.get("profile") or {}).get("name") if isinstance(contact, dict) else None
                    if display_name:
                        defaults["display_name"] = display_name[:255]

                    # Optional last4 (support-only)
                    defaults["wa_last4"] = wa_norm[-4:] if len(wa_norm) >= 4 else None

                    obj, created = WAUser.objects.get_or_create(wa_id_hash=wa_hash, defaults=defaults)
                    # Update last_seen on any contact
                    WAUser.objects.filter(pk=obj.pk).update(last_seen=timezone.now())

                    if created:
                        try:
                            intro = get_intro_message(obj.locale or defaults.get("locale") or "he-IL")
                            send_whatsapp_text(wa_norm, intro)
                        except Exception:
                            logger.exception("failed to send intro message to %s", wa_norm)

                    processed += 1

        return JsonResponse({"status": "ok", "processed": processed})
