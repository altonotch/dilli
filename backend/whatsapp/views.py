from __future__ import annotations
import hmac
import json
import logging
from hashlib import sha256

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone, translation
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework import status
from django.utils.translation import gettext as _

from .models import WAUser, DealLookupSession
from .utils import (
    normalize_wa_id,
    compute_wa_hash,
    detect_locale,
    get_intro_message,
    get_intro_buttons,
    send_whatsapp_text,
    send_whatsapp_buttons,
    parse_language_choice,
    get_language_prompt,
    normalize_locale,
    is_add_command,
    is_find_command,
)
from .deal_flow import (
    start_add_deal_flow,
    handle_deal_flow_response,
    FlowMessage,
)
from .search_flow import (
    start_find_deal_flow,
    handle_find_deal_text,
    handle_find_deal_location,
)
from .throttling import IPRateThrottle, WaHashRateThrottle
from .unit_translations import get_unit_label_for_locale

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
        logger.info("Received WhatsApp webhook headers=%s", dict(request.headers))
        if not _verify_signature(request):
            logger.warning("Invalid signature on webhook")
            return JsonResponse({"detail": "invalid signature"}, status=status.HTTP_403_FORBIDDEN)

        try:
            payload = json.loads(request.body.decode("utf-8"))
            logger.debug("Webhook payload: %s", payload)
        except Exception:
            logger.exception("Failed to decode webhook JSON")
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
                    logger.info("Processing message: wa_raw=%s message=%s", wa_raw, msg)
                    if not wa_norm:
                        logger.warning("Unable to normalize WhatsApp id: %s", wa_raw)
                        continue
                    wa_hash = compute_wa_hash(wa_norm)

                    defaults = {
                        "consent_ts": timezone.now(),
                        "role": WAUser.Roles.USER,
                        "wa_number": wa_norm,
                        "wa_last4": wa_norm[-4:] if len(wa_norm) >= 4 else "",
                    }
                    # Optional locale detection and/or explicit language choice
                    try:
                        body_text = ""
                        message_type = msg.get("type")
                        if message_type == "text" and isinstance(msg.get("text"), dict):
                            body_text = (msg.get("text") or {}).get("body", "")
                    except Exception:
                        body_text = ""
                        message_type = msg.get("type")

                    button_reply_id = None
                    if msg.get("type") == "interactive" and isinstance(msg.get("interactive"), dict):
                        interactive = msg["interactive"]
                        if interactive.get("type") == "button_reply":
                            button_reply = interactive.get("button_reply") or {}
                            button_reply_id = button_reply.get("id")

                    if button_reply_id and button_reply_id.startswith("unit_type:"):
                        unit_slug = button_reply_id.split(":", 1)[1]
                        unit_value = get_unit_label_for_locale(unit_slug, current_locale)
                        if unit_value:
                            body_text = unit_value
                            button_reply_id = None

                    lang_choice = parse_language_choice(body_text)
                    defaults["locale"] = lang_choice or detect_locale(body_text or "")

                    # Optional display name
                    contact = contacts.get(wa_norm) or (value.get("contacts", [{}])[0] if value.get("contacts") else {})
                    display_name = (contact.get("profile") or {}).get("name") if isinstance(contact, dict) else None
                    if display_name:
                        defaults["display_name"] = display_name[:255]

                    # Optional last4 (support-only)
                    defaults["wa_last4"] = wa_norm[-4:] if len(wa_norm) >= 4 else None

                    obj, created = WAUser.objects.get_or_create(wa_id_hash=wa_hash, defaults=defaults)
                    logger.info(
                        "Resolved WAUser id=%s created=%s wa_number=%s locale=%s",
                        obj.pk,
                        created,
                        wa_norm,
                        defaults.get("locale"),
                    )
                    # Update contact fields on any message
                    WAUser.objects.filter(pk=obj.pk).update(
                        last_seen=timezone.now(),
                        wa_number=wa_norm,
                        wa_last4=wa_norm[-4:] if len(wa_norm) >= 4 else None,
                    )

                    # Determine current effective locale
                    current_locale = normalize_locale(getattr(obj, 'locale', None) or defaults.get('locale') or 'he')

                    try:
                        if button_reply_id == "add_deal" or is_add_command(body_text):
                            question = start_add_deal_flow(obj, current_locale)
                            logger.info("Routing to add-deal flow for %s", wa_norm)
                            _send_flow_message(wa_norm, question)
                            processed += 1
                            continue
                        if button_reply_id == "find_deal" or is_find_command(body_text):
                            question = start_find_deal_flow(obj, current_locale)
                            logger.info("Routing to find-deal flow for %s", wa_norm)
                            send_whatsapp_text(wa_norm, question)
                            processed += 1
                            continue

                        flow_reply = handle_deal_flow_response(obj, current_locale, body_text)
                        if flow_reply:
                            logger.info("Deal flow response for %s: %s", wa_norm, flow_reply)
                            _send_flow_message(wa_norm, flow_reply)
                            processed += 1
                            continue

                        if lang_choice:
                            # User explicitly chose a language: persist and acknowledge with an intro
                            new_locale = normalize_locale(lang_choice)
                            if new_locale != current_locale:
                                WAUser.objects.filter(pk=obj.pk).update(locale=new_locale)
                                current_locale = new_locale
                            intro = get_intro_message(current_locale)
                            buttons = get_intro_buttons(current_locale)
                            sent = send_whatsapp_buttons(wa_norm, intro, buttons)
                            if not sent:
                                send_whatsapp_text(wa_norm, intro)
                            processed += 1
                            continue
                        elif created:
                            # New user without explicit choice: ask to select language
                            prompt = get_language_prompt()
                            send_whatsapp_text(wa_norm, prompt)
                            processed += 1
                            continue

                        # Deal lookup flow (text)
                        lookup_reply = handle_find_deal_text(obj, current_locale, body_text)
                        if lookup_reply:
                            logger.info("Deal lookup response for %s: %s", wa_norm, lookup_reply)
                            send_whatsapp_text(wa_norm, lookup_reply)
                            processed += 1
                            continue

                        # Location-based find flow
                        if message_type == "location":
                            location_reply = handle_find_deal_location(
                                obj,
                                current_locale,
                                msg.get("location") or {},
                            )
                            if location_reply:
                                logger.info("Location-based lookup for %s: %s", wa_norm, location_reply)
                                send_whatsapp_text(wa_norm, location_reply)
                                processed += 1
                                continue
                    except Exception:
                        logger.exception("failed to send onboarding/flow message to %s", wa_norm)

                    intro = get_intro_message(current_locale)
                    buttons = get_intro_buttons(current_locale)
                    logger.info("Sending fallback intro/help to %s", wa_norm)
                    sent = send_whatsapp_buttons(wa_norm, intro, buttons)
                    if not sent:
                        send_whatsapp_text(wa_norm, intro)
                    processed += 1

        logger.info("Completed webhook processing processed=%s", processed)
        return JsonResponse({"status": "ok", "processed": processed})
def _send_flow_message(recipient: str, payload: FlowMessage | str) -> None:
    if isinstance(payload, FlowMessage):
        text = payload.text
        buttons = payload.buttons or []
        if buttons:
            sent = send_whatsapp_buttons(recipient, text, buttons)
            if not sent:
                send_whatsapp_text(recipient, text)
        else:
            send_whatsapp_text(recipient, text)
    else:
        send_whatsapp_text(recipient, payload)
