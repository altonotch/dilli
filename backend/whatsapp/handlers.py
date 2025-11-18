from __future__ import annotations

import structlog
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from django.utils import timezone
from structlog import contextvars as structlog_contextvars

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
from .utils import (
    normalize_locale,
    is_add_command,
    is_find_command,
    get_intro_message,
    get_intro_buttons,
    get_language_prompt,
    parse_language_choice,
    detect_locale,
    compute_wa_hash,
)
from .unit_translations import get_unit_label_for_locale
from .models import WAUser


logger = structlog.get_logger(__name__)


# Types used by the handler registry
StatePayload = FlowMessage | str
HandlerFunc = Callable[["UserMessageContext", dict], Optional[StatePayload]]


# Context object shared across handlers and view
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

    # Language choice intent from the raw text (do not apply locale change here)
    lang_choice = parse_language_choice(body_text)

    # Only auto-detect language for non-numeric messages; numbers shouldn't flip locale
    stripped = (body_text or "").strip()
    is_numeric_only = bool(stripped) and stripped.isdigit()
    inferred_locale = detect_locale(body_text) if not is_numeric_only else None

    defaults = {
        "consent_ts": timezone.now(),
        "role": WAUser.Roles.USER,
        "wa_number": wa_norm,
        "wa_last4": wa_norm[-4:] if len(wa_norm) >= 4 else "",
        # Do not use lang_choice here; only rely on detection for non-numeric input
        "locale": inferred_locale or "en",
    }

    # Optional display name from contacts
    contact = contacts.get(wa_norm) or (
        value.get("contacts", [{}])[0] if value.get("contacts") else {}
    )
    display_name = (
        (contact.get("profile") or {}).get("name")
        if isinstance(contact, dict)
        else None
    )
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
    # If the user already has a stored locale, prefer it; otherwise use non-numeric detection (or default to en)
    if getattr(obj, "locale", None):
        current_locale = normalize_locale(obj.locale)
    else:
        current_locale = normalize_locale(inferred_locale or "en")

    # Post-process unit type buttons into text in the current locale
    if (
        button_reply_id
        and isinstance(button_reply_id, str)
        and button_reply_id.startswith("unit_type:")
    ):
        try:
            unit_slug = button_reply_id.split(":", 1)[1]
            unit_value = get_unit_label_for_locale(unit_slug, current_locale)
            if unit_value:
                body_text = unit_value
                button_reply_id = None  # Ensure normal text handling continues
        except Exception:
            # Do not fail the whole handling if something goes wrong here
            logger.exception("Failed to map unit_type button to text for %s", wa_norm)

    structlog_contextvars.bind_contextvars(user_id=str(obj.pk))

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


def _state_start_add(ctx: "UserMessageContext", _msg: dict) -> Optional[StatePayload]:
    if ctx.button_reply_id == "add_deal" or is_add_command(ctx.body_text):
        return start_add_deal_flow(ctx.user, ctx.current_locale)
    return None


def _state_start_find(ctx: "UserMessageContext", _msg: dict) -> Optional[StatePayload]:
    if ctx.button_reply_id == "find_deal" or is_find_command(ctx.body_text):
        return start_find_deal_flow(ctx.user, ctx.current_locale)
    return None


def _state_deal_flow_cont(
    ctx: "UserMessageContext", _msg: dict
) -> Optional[StatePayload]:
    return handle_deal_flow_response(ctx.user, ctx.current_locale, ctx.body_text)


def _state_lang_chosen(ctx: "UserMessageContext", _msg: dict) -> Optional[StatePayload]:
    if not ctx.lang_choice:
        return None
    new_locale = normalize_locale(ctx.lang_choice)
    if new_locale != ctx.current_locale:
        WAUser.objects.filter(pk=ctx.user.pk).update(locale=new_locale)
        ctx.current_locale = new_locale
    intro = get_intro_message(ctx.current_locale)
    buttons = get_intro_buttons(ctx.current_locale)
    return FlowMessage(text=intro, buttons=buttons)


def _state_new_user(ctx: "UserMessageContext", _msg: dict) -> Optional[StatePayload]:
    if ctx.created:
        return get_language_prompt()
    return None


def _state_find_text(ctx: "UserMessageContext", _msg: dict) -> Optional[StatePayload]:
    return handle_find_deal_text(ctx.user, ctx.current_locale, ctx.body_text)


def _state_find_location(
    ctx: "UserMessageContext", msg: dict
) -> Optional[StatePayload]:
    if ctx.message_type == "location":
        return handle_find_deal_location(
            ctx.user, ctx.current_locale, msg.get("location") or {}
        )
    return None


# Fallback payload when no handler matches
def fallback_payload(ctx: "UserMessageContext") -> StatePayload:
    intro = get_intro_message(ctx.current_locale)
    buttons = get_intro_buttons(ctx.current_locale)
    return FlowMessage(text=intro, buttons=buttons)


# Helper to log concise response info
def summarize_payload(payload: StatePayload) -> str:
    try:
        if isinstance(payload, FlowMessage):
            text = payload.text or ""
            text_trim = (text[:120] + "…") if len(text) > 120 else text
            btns = payload.buttons or []
            return f"FlowMessage(text='{text_trim}', buttons={len(btns)})"
        else:
            text = payload or ""
            text_trim = (text[:120] + "…") if len(text) > 120 else text
            return f"Text('{text_trim}')"
    except Exception:
        return "<unprintable payload>"


# Ordered handler registry (first match wins)
HANDLERS: Tuple[Tuple[str, HandlerFunc], ...] = (
    ("START_ADD", _state_start_add),
    ("START_FIND", _state_start_find),
    ("DEAL_FLOW_CONT", _state_deal_flow_cont),
    ("LANG_CHOSEN", _state_lang_chosen),
    ("NEW_USER", _state_new_user),
    ("FIND_TEXT", _state_find_text),
    ("FIND_LOCATION", _state_find_location),
)
