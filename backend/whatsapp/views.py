from __future__ import annotations
import hmac
import json
import logging
from hashlib import sha256
from dataclasses import dataclass

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


@dataclass
class UserMessageContext:
    """Aggregates all per-message data needed for routing state machine."""
    user: WAUser
    wa_norm: str
    wa_hash: str
    body_text: str
    message_type: str | None
    button_reply_id: str | None
    lang_choice: str | None
    current_locale: str
    created: bool


def _build_user_context(
    *,
    wa_norm: str,
    msg: dict,
    contacts: dict,
    value: dict,
) -> UserMessageContext:
    """Create or update WAUser and extract message attributes.

    This function centralizes user resolution, locale detection, message parsing,
    and returns a compact context object for the state machine in the view.
    """
    wa_hash = compute_wa_hash(wa_norm)

    # Parse message basics
    message_type = msg.get("type")
    body_text = ""
    if message_type == "text" and isinstance(msg.get("text"), dict):
        body_text = (msg.get("text") or {}).get("body", "")

    button_reply_id = None
    if msg.get("type") == "interactive" and isinstance(msg.get("interactive"), dict):
        interactive = msg["interactive"]
        if interactive.get("type") == "button_reply":
            button_reply = interactive.get("button_reply") or {}
            button_reply_id = button_reply.get("id")

    # Language choice and default locale guess from the raw text
    lang_choice = parse_language_choice(body_text)

    defaults = {
        "consent_ts": timezone.now(),
        "role": WAUser.Roles.USER,
        "wa_number": wa_norm,
        "wa_last4": wa_norm[-4:] if len(wa_norm) >= 4 else "",
        "locale": lang_choice or detect_locale(body_text or ""),
    }

    # Optional display name from contacts
    contact = contacts.get(wa_norm) or (value.get("contacts", [{}])[0] if value.get("contacts") else {})
    display_name = (contact.get("profile") or {}).get("name") if isinstance(contact, dict) else None
    if display_name:
        defaults["display_name"] = display_name[:255]

    # Create or fetch the user
    obj, created = WAUser.objects.get_or_create(wa_id_hash=wa_hash, defaults=defaults)

    # Keep contact fields up to date
    WAUser.objects.filter(pk=obj.pk).update(
        last_seen=timezone.now(),
        wa_number=wa_norm,
        wa_last4=wa_norm[-4:] if len(wa_norm) >= 4 else None,
    )

    # Determine the effective locale
    current_locale = normalize_locale(getattr(obj, "locale", None) or defaults.get("locale") or "he")

    # Post-process unit type buttons into text in the current locale
    if button_reply_id and isinstance(button_reply_id, str) and button_reply_id.startswith("unit_type:"):
        try:
            unit_slug = button_reply_id.split(":", 1)[1]
            unit_value = get_unit_label_for_locale(unit_slug, current_locale)
            if unit_value:
                body_text = unit_value
                button_reply_id = None  # Ensure normal text handling continues
        except Exception:
            # Do not fail the whole handling if something goes wrong here
            logger.exception("Failed to map unit_type button to text for %s", wa_norm)

    return UserMessageContext(
        user=obj,
        wa_norm=wa_norm,
        wa_hash=wa_hash,
        body_text=body_text,
        message_type=message_type,
        button_reply_id=button_reply_id,
        lang_choice=lang_choice,
        current_locale=current_locale,
        created=created,
    )


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
        if mode == "subscribe":
            expected = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "")
            if expected and token != expected:
                logger.warning(
                    "Webhook verify token mismatch expected=%s provided=%s",
                    expected,
                    token,
                )
            if challenge:
                return HttpResponse(challenge, content_type="text/plain")
            return HttpResponse(status=status.HTTP_200_OK)
        return HttpResponse(status=status.HTTP_200_OK)

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

                    # Resolve user and message context once
                    ctx = _build_user_context(wa_norm=wa_norm, msg=msg, contacts=contacts, value=value)
                    logger.info(
                        "Resolved WAUser id=%s created=%s wa_number=%s locale=%s",
                        ctx.user.pk,
                        ctx.created,
                        ctx.wa_norm,
                        ctx.current_locale,
                    )

                    # State machine: decide which handler should run for this message
                    state = None
                    try:
                        if ctx.button_reply_id == "add_deal" or is_add_command(ctx.body_text):
                            state = "START_ADD"
                            logger.info("State=%s for %s", state, ctx.wa_norm)
                            question = start_add_deal_flow(ctx.user, ctx.current_locale)
                            _send_flow_message(ctx.wa_norm, question)
                            processed += 1
                            continue

                        if ctx.button_reply_id == "find_deal" or is_find_command(ctx.body_text):
                            state = "START_FIND"
                            logger.info("State=%s for %s", state, ctx.wa_norm)
                            question = start_find_deal_flow(ctx.user, ctx.current_locale)
                            send_whatsapp_text(ctx.wa_norm, question)
                            processed += 1
                            continue

                        flow_reply = handle_deal_flow_response(ctx.user, ctx.current_locale, ctx.body_text)
                        if flow_reply:
                            state = "DEAL_FLOW_CONT"
                            logger.info("State=%s for %s: %s", state, ctx.wa_norm, flow_reply)
                            _send_flow_message(ctx.wa_norm, flow_reply)
                            processed += 1
                            continue

                        if ctx.lang_choice:
                            state = "LANG_CHOSEN"
                            logger.info("State=%s for %s", state, ctx.wa_norm)
                            # User explicitly chose a language: persist and acknowledge with an intro
                            new_locale = normalize_locale(ctx.lang_choice)
                            if new_locale != ctx.current_locale:
                                WAUser.objects.filter(pk=ctx.user.pk).update(locale=new_locale)
                                ctx.current_locale = new_locale
                            intro = get_intro_message(ctx.current_locale)
                            buttons = get_intro_buttons(ctx.current_locale)
                            sent = send_whatsapp_buttons(ctx.wa_norm, intro, buttons)
                            if not sent:
                                send_whatsapp_text(ctx.wa_norm, intro)
                            processed += 1
                            continue

                        if ctx.created:
                            state = "NEW_USER"
                            logger.info("State=%s for %s", state, ctx.wa_norm)
                            # New user without explicit choice: ask to select language
                            prompt = get_language_prompt()
                            send_whatsapp_text(ctx.wa_norm, prompt)
                            processed += 1
                            continue

                        # Deal lookup flow (text)
                        lookup_reply = handle_find_deal_text(ctx.user, ctx.current_locale, ctx.body_text)
                        if lookup_reply:
                            state = "FIND_TEXT"
                            logger.info("State=%s for %s: %s", state, ctx.wa_norm, lookup_reply)
                            send_whatsapp_text(ctx.wa_norm, lookup_reply)
                            processed += 1
                            continue

                        # Location-based find flow
                        if ctx.message_type == "location":
                            state = "FIND_LOCATION"
                            logger.info("State=%s for %s", state, ctx.wa_norm)
                            location_reply = handle_find_deal_location(
                                ctx.user,
                                ctx.current_locale,
                                msg.get("location") or {},
                            )
                            if location_reply:
                                send_whatsapp_text(ctx.wa_norm, location_reply)
                                processed += 1
                                continue
                    except Exception:
                        logger.exception("failed to send onboarding/flow message to %s", ctx.wa_norm)

                    # Fallback: intro/help
                    state = state or "FALLBACK"
                    intro = get_intro_message(ctx.current_locale)
                    buttons = get_intro_buttons(ctx.current_locale)
                    logger.info("State=%s Sending fallback intro/help to %s", state, ctx.wa_norm)
                    sent = send_whatsapp_buttons(ctx.wa_norm, intro, buttons)
                    if not sent:
                        send_whatsapp_text(ctx.wa_norm, intro)
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
