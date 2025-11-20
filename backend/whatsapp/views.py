from __future__ import annotations
import hmac
import json
import structlog
from hashlib import sha256

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework import status

from .utils import (
    normalize_wa_id,
    send_whatsapp_text,
    send_whatsapp_buttons,
)
from .deal_flow import FlowMessage
from .throttling import IPRateThrottle, WaHashRateThrottle
from structlog import contextvars as structlog_contextvars
from .handlers import (
    HANDLERS,
    fallback_payload,
    summarize_payload,
    _build_user_context,
)


logger = structlog.get_logger(__name__)


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
        if mode == "subscribe":
            expected = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "")
            if expected and token != expected:
                logger.warning(
                    "webhook_verify_token_mismatch",
                    expected=expected,
                    provided=token,
                )
            if challenge:
                return HttpResponse(challenge, content_type="text/plain")
            return HttpResponse(status=status.HTTP_200_OK)
        return HttpResponse(status=status.HTTP_200_OK)

    def post(self, request: HttpRequest) -> JsonResponse:
        logger.info("webhook_request_received", headers=dict(request.headers))
        if not _verify_signature(request):
            logger.warning("webhook_invalid_signature")
            return JsonResponse({"detail": "invalid signature"}, status=status.HTTP_403_FORBIDDEN)

        try:
            payload = json.loads(request.body.decode("utf-8"))
            logger.debug("webhook_payload_decoded", payload=payload)
        except Exception:
            logger.exception("webhook_json_decode_failed")
            return JsonResponse({"detail": "bad json"}, status=status.HTTP_400_BAD_REQUEST)

        processed: int = 0
        # WhatsApp webhook structure: entry -> changes -> value -> messages[]
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", []) or []
                contacts = {c.get("wa_id"): c for c in value.get("contacts", [])}
                for msg in messages:
                    structlog_contextvars.clear_contextvars()
                    wa_raw = str(msg.get("from", ""))
                    wa_norm = normalize_wa_id(wa_raw)
                    logger.info("webhook_processing_message", wa_raw=wa_raw, message=msg)
                    if not wa_norm:
                        logger.warning("webhook_unable_to_normalize_wa", wa_raw=wa_raw)
                        continue

                    # Resolve user and message context once
                    ctx = _build_user_context(wa_norm=wa_norm, msg=msg, contacts=contacts, value=value)
                    logger.info(
                        "webhook_user_resolved",
                        user_id=ctx.user.pk,
                        created=ctx.created,
                        wa_number=ctx.wa_norm,
                        locale=ctx.current_locale,
                    )

                    # Generic state-machine evaluation via handlers
                    state = None
                    handled = False
                    try:
                        for state_name, handler in HANDLERS:
                            payload = handler(ctx, msg)
                            if payload:
                                state = state_name
                                logger.info("handler_state", state=state, wa_hash=ctx.wa_hash)
                                _send_flow_message(ctx.wa_norm, payload)
                                logger.info(
                                    "handler_response_sent",
                                    wa_hash=ctx.wa_hash,
                                    payload=summarize_payload(payload),
                                )
                                processed += 1
                                handled = True
                                break
                            else:
                                logger.info("handler_no_response", state=state_name, wa_hash=ctx.wa_hash)
                    except Exception:
                        logger.exception("handler_send_failed", wa_hash=ctx.wa_hash)

                    if handled:
                        continue

                    # Fallback: intro/help
                    state = state or "FALLBACK"
                    fallback = fallback_payload(ctx)
                    logger.info("handler_fallback_intro", state=state, wa_hash=ctx.wa_hash)
                    _send_flow_message(ctx.wa_norm, fallback)
                    logger.info(
                        "handler_fallback_response",
                        wa_hash=ctx.wa_hash,
                        payload=summarize_payload(fallback),
                    )
                    processed += 1

        logger.info("webhook_processing_completed", processed=processed)
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
