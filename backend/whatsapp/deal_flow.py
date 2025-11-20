from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence
import structlog

from dataclasses import dataclass
from django.db.models import Q
from django.utils import translation, timezone
from django.utils.translation import gettext as _

from catalog.models import Product
from stores.models import Store, City, normalize_store_text
from pricing.models import PriceReport

from .models import DealReportSession, WAUser
from .unit_translations import resolve_unit_translation, select_unit_for_locale, get_unit_by_slug

QUESTION_SEQUENCE = [
    DealReportSession.Steps.STORE,
    DealReportSession.Steps.BRANCH,
    DealReportSession.Steps.CITY,
    DealReportSession.Steps.STORE_CONFIRM,
    DealReportSession.Steps.PRODUCT,
    DealReportSession.Steps.BRAND,
    DealReportSession.Steps.UNIT_TYPE,
    DealReportSession.Steps.UNIT_QUANTITY,
    DealReportSession.Steps.PRICE,
    DealReportSession.Steps.UNITS,
    DealReportSession.Steps.CLUB,
    DealReportSession.Steps.LIMIT,
    DealReportSession.Steps.CART,
]

logger = structlog.get_logger(__name__)

CANCEL_KEYWORDS = {"cancel", "stop", "בטל", "ביטול", "סיים", "סיום"}
YES_KEYWORDS = {"yes", "y", "yeah", "כן", "yep", "si"}
NO_KEYWORDS = {"no", "n", "not", "לא", "nope", "אין"}
BRAND_SKIP_KEYWORDS = {
    "skip",
    "n/a",
    "na",
    "none",
    "unknown",
    "dont know",
    "don't know",
    "no brand",
    "generic",
    "דלג",
    "דלגו",
    "אין מותג",
    "בלי מותג",
    "לא יודע",
    "לא ידוע",
}
BRANCH_SKIP_KEYWORDS = {
    "skip",
    "n/a",
    "na",
    "none",
    "unknown",
    "dont know",
    "don't know",
    "no branch",
    "generic",
    "דלג",
    "דלגו",
    "אין",
    "אין סניף",
    "בלי סניף",
    "לא יודע",
    "לא ידוע",
}
MAX_STORE_CHOICES = 5
HEBREW_DOUBLE_FORMS = (("וו", "ו"), ("יי", "י"))
CITY_CHANGE_KEYWORDS_EN = {"change city", "change", "other city"}
CITY_CHANGE_KEYWORDS_HE = {"שנה עיר", "שנו עיר", "עיר אחרת", "שינוי עיר"}


@dataclass
class FlowMessage:
    text: str
    buttons: Optional[list[dict]] = None


def _contains_hebrew(value: str) -> bool:
    return any("\u0590" <= ch <= "\u05FF" for ch in value or "")


def _contains_latin(value: str) -> bool:
    return any(
        ("a" <= ch <= "z") or ("A" <= ch <= "Z")
        for ch in value or ""
    )


def _city_query_values(data: dict) -> list[str]:
    values: list[str] = []
    for key in ("city", "city_he", "city_en"):
        val = _normalize_text(data.get(key))
        if val and val not in values:
            values.append(val)
    return values


def _city_from_session(data: dict) -> Optional[City]:
    city_id = data.get("city_id")
    if city_id:
        return City.objects.filter(pk=city_id).first()
    return None


def _build_city_filter(values: Sequence[str]) -> Q:
    condition = Q()
    for city in values:
        condition |= (
            Q(city__iexact=city)
            | Q(city_he__iexact=city)
            | Q(city_en__iexact=city)
            | Q(city_obj__name_he__iexact=city)
            | Q(city_obj__name_en__iexact=city)
        )
    return condition


def start_add_deal_flow(user: WAUser, locale: str) -> FlowMessage:
    DealReportSession.objects.filter(user=user, is_active=True).update(
        is_active=False, step=DealReportSession.Steps.CANCELED
    )
    session = DealReportSession.objects.create(user=user)
    return _question_prompt(session, locale)


def handle_deal_flow_response(user: WAUser, locale: str, message_text: Optional[str]) -> Optional[str]:
    session = (
        DealReportSession.objects.filter(user=user, is_active=True)
        .order_by("-updated_at")
        .first()
    )
    if not session:
        return None

    text = (message_text or "").strip()
    with translation.override(locale):
        if not text:
            return _("Please send a reply so I can continue.")

        lower = text.lower()
        if lower in CANCEL_KEYWORDS:
            session.is_active = False
            session.step = DealReportSession.Steps.CANCELED
            session.save(update_fields=["is_active", "step", "updated_at"])
            return _("Okay, I canceled that deal. Tap “Add a deal” anytime to start again.")

        handler = _STEP_HANDLERS.get(session.step)
        if not handler:
            session.is_active = False
            session.step = DealReportSession.Steps.COMPLETE
            session.save(update_fields=["is_active", "step", "updated_at"])
            return _("Thanks! You can start a new deal anytime.")

        next_prompt = handler(session, text)
        if isinstance(next_prompt, str):
            return next_prompt
        if isinstance(next_prompt, FlowMessage):
            return next_prompt

        # If handler returned None, we already advanced and should ask next question
        if session.step in QUESTION_SEQUENCE:
            return _question_prompt(session, locale)

        summary = _format_summary(session.data, locale)
        try:
            _persist_price_report(session, user)
        except Exception:
            logger.exception("persist_price_report_failed", session_id=session.pk)
        return FlowMessage(summary)


def _unit_type_buttons(locale: str) -> list[dict]:
    preferred = ["liter", "kilogram", "unit"]
    buttons = []
    for slug in preferred:
        entry = get_unit_by_slug(slug)
        if not entry:
            continue
        title = entry["he"] if locale.startswith("he") else entry["en"]
        buttons.append({"id": f"unit_type:{slug}", "title": title[:20]})
    return buttons


def _get_user_city_object(user: WAUser) -> Optional[City]:
    city = getattr(user, "city_obj", None)
    if city:
        return city
    city_name = (user.city or "").strip()
    if not city_name:
        return None
    city = _match_city(city_name)
    if not city:
        city = City.objects.create(
            name_he=city_name,
            name_en=city_name,
        )
    if city:
        WAUser.objects.filter(pk=user.pk).update(city_obj=city, city=city.display_name)
        user.city_obj = city
        user.city = city.display_name
    return city


def _assign_user_city(session: DealReportSession, city: Optional[City]) -> None:
    if not city:
        return
    if (
        session.user.city_obj_id == city.id
        and (session.user.city or "").strip() == city.display_name
    ):
        return
    WAUser.objects.filter(pk=session.user.pk).update(
        city_obj=city,
        city=city.display_name,
    )
    session.user.city_obj = city
    session.user.city = city.display_name


def _city_prompt(session: DealReportSession, locale: str) -> FlowMessage:
    city_obj = _get_user_city_object(session.user)
    default_city = city_obj.display_name if city_obj else ""
    with translation.override(locale):
        if not default_city:
            return FlowMessage(_("Which city is the store in?"))
        change_label = _("Change city")
        _update_data(session, city_change_label=change_label)
        prompt = _("Use your saved city (%(city)s) or choose another city.") % {"city": default_city}
        buttons = [
            {"id": "city_default", "title": default_city[:20]},
            {"id": "city_change", "title": change_label[:20]},
        ]
        return FlowMessage(prompt, buttons=buttons)


def _question_prompt(session: DealReportSession, locale: str) -> FlowMessage:
    step = session.step
    data = session.data or {}
    with translation.override(locale):
        if step == DealReportSession.Steps.STORE_CONFIRM:
            return FlowMessage(_format_store_choice_prompt(data))
        if step == DealReportSession.Steps.CITY:
            return _city_prompt(session, locale)

        prompts = {
            DealReportSession.Steps.STORE: _(
                "Which store or chain is this deal from?\nExample: “Shufersal” or “Rami Levy”."
            ),
            DealReportSession.Steps.BRANCH: _(
                "Which branch or neighborhood is it? Example: “Givat Tal” or “Dizengoff 50”. Type \"skip\" if you’re not sure."
            ),
            DealReportSession.Steps.PRODUCT: _(
                "What product is this? (We’ll ask about size in the next questions.)"
            ),
            DealReportSession.Steps.BRAND: _(
                "Which brand makes this product? Reply with the brand name or type \"skip\" if you're not sure."
            ),
            DealReportSession.Steps.UNIT_TYPE: _(
                "What unit is the package? (e.g., liter, kilogram, pack)."
            ),
            DealReportSession.Steps.UNIT_QUANTITY: _(
                "How many of that unit are in the package? Reply with a number (e.g., 1, 1.5, 2)."
            ),
            DealReportSession.Steps.PRICE: _(
                "What is the price? Reply with numbers only (e.g., 4.90)."
            ),
            DealReportSession.Steps.UNITS: _(
                "How many units does this price cover? Reply with a number (default 1)."
            ),
            DealReportSession.Steps.CLUB: _(
                "Is this deal only for club/loyalty members? Reply “yes” or “no”."
            ),
            DealReportSession.Steps.LIMIT: _(
                "Is there a quantity limit per shopper? Reply with a number or “no”."
            ),
            DealReportSession.Steps.CART: _(
                "Is there a minimum cart total to unlock this deal? Reply with an amount or “no”."
            ),
        }
        text = prompts.get(step, _("Thanks!"))
        buttons = None
        if step == DealReportSession.Steps.UNIT_TYPE:
            guidance = _("Tap one of the buttons or type another unit.")
            text = f"{text}\n\n{guidance}"
            buttons = _unit_type_buttons(locale)
        return FlowMessage(text=text, buttons=buttons)


def _format_store_choice_prompt(data: dict) -> str:
    choices: Sequence[dict] = data.get("store_choices") or []
    store_name = data.get("store_name") or _("this store")
    city_values = _city_query_values(data)
    city_obj = _city_from_session(data)
    city_label = city_obj.display_name if city_obj else (city_values[0] if city_values else "")
    if not choices:
        return _("Please tell me which branch %(store)s is so I can match the right location.") % {
            "store": store_name,
        }
    lines = [
        _("I found a few stores named %(store)s in %(city)s:") % {
            "store": store_name,
            "city": city_label or _("this city"),
        }
    ]
    for idx, choice in enumerate(choices, 1):
        label = choice.get("label") or choice.get("name") or store_name
        detail = choice.get("address") or choice.get("city") or ""
        if detail:
            lines.append(_("%(index)s) %(label)s — %(detail)s") % {"index": idx, "label": label, "detail": detail})
        else:
            lines.append(_("%(index)s) %(label)s") % {"index": idx, "label": label})
    lines.append(
        _("Reply with the matching number, or type the branch/address if it's not in this list.")
    )
    return "\n".join(lines)


def _advance(session: DealReportSession, target_step: str | None = None) -> None:
    try:
        if target_step:
            session.step = target_step
        else:
            idx = QUESTION_SEQUENCE.index(session.step)
            session.step = QUESTION_SEQUENCE[idx + 1]
    except (ValueError, IndexError):
        session.step = DealReportSession.Steps.COMPLETE
        session.is_active = False
    session.save(update_fields=["step", "is_active", "data", "updated_at"])


def _update_data(session: DealReportSession, **updates) -> None:
    data = dict(session.data or {})
    data.update(updates)
    session.data = data


def _handle_store(session: DealReportSession, text: str) -> None:
    _update_data(session, store_name=text, store_id=None, store_detail=None, store_choices=[])
    _advance(session)


def _handle_branch(session: DealReportSession, text: str) -> None:
    cleaned = text.strip()
    lower = cleaned.lower()
    if not cleaned or lower in BRANCH_SKIP_KEYWORDS:
        _update_data(session, store_detail="")
    else:
        _update_data(session, store_detail=cleaned)
    _advance(session)


def _handle_city(session: DealReportSession, text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return _("Please tell me which city this store is in.")
    data = session.data or {}
    change_label = (data.get("city_change_label") or "").strip().lower()
    lower = cleaned.lower()
    if change_label and lower == change_label:
        return _("Okay, type the city name for this deal.")
    if lower in CITY_CHANGE_KEYWORDS_EN or lower in CITY_CHANGE_KEYWORDS_HE:
        return _("Okay, type the city name for this deal.")
    updates = {"city": cleaned, "city_change_label": None}
    if _contains_hebrew(cleaned):
        updates["city_he"] = cleaned
    if _contains_latin(cleaned):
        updates["city_en"] = cleaned
    _update_data(session, **updates)

    _ensure_city_reference(session)
    if _maybe_request_store_choice(session):
        return None
    _advance(session, DealReportSession.Steps.PRODUCT)
    return None


def _ensure_city_reference(session: DealReportSession) -> Optional[City]:
    data = session.data or {}
    city = _city_from_session(data)
    if city:
        _update_data(session, city_he=city.name_he, city_en=city.name_en, city=city.display_name)
        _assign_user_city(session, city)
        return city

    city_he = _normalize_text(data.get("city_he"))
    city_en = _normalize_text(data.get("city_en"))
    fallback = _normalize_text(data.get("city"))

    city = None
    for candidate in (city_he, city_en, fallback):
        if candidate:
            city = _match_city(candidate)
            if city:
                break

    if not city:
        name_he = city_he or fallback or city_en
        name_en = city_en or fallback or city_he
        if not (name_he or name_en):
            return None
        city = City.objects.create(
            name_he=name_he or name_en,
            name_en=name_en or name_he,
        )

    _update_data(
        session,
        city_id=str(city.id),
        city_he=city.name_he,
        city_en=city.name_en,
        city=city.display_name,
    )
    _assign_user_city(session, city)
    return city


def _maybe_request_store_choice(session: DealReportSession) -> bool:
    data = session.data or {}
    store_name = _normalize_text(data.get("store_name"))
    if not store_name:
        return False

    candidates = _find_store_candidates(store_name, data)
    if len(candidates) <= 1:
        if candidates:
            _update_data(session, store_id=str(candidates[0].id))
        _update_data(session, store_choices=[])
        return False

    serialized = [
        {
            "id": str(store.id),
            "label": store.display_name or store.name,
            "address": store.address or "",
            "city": store.city or store.city_en or store.city_he or "",
        }
        for store in candidates[:MAX_STORE_CHOICES]
    ]
    _update_data(session, store_choices=serialized)
    _advance(session, DealReportSession.Steps.STORE_CONFIRM)
    return True


def _handle_store_confirm(session: DealReportSession, text: str) -> Optional[str]:
    data = session.data or {}
    choices: Sequence[dict] = data.get("store_choices") or []
    cleaned = text.strip()
    if cleaned.isdigit() and choices:
        idx = int(cleaned) - 1
        if 0 <= idx < len(choices):
            selection = choices[idx]
            _update_data(session, store_id=selection.get("id"), store_choices=[])
            _advance(session, DealReportSession.Steps.PRODUCT)
            return None
        return _("Please reply with a number between 1 and %(count)s, or type the branch name.") % {
            "count": len(choices)
        }

    if cleaned:
        _update_data(session, store_detail=cleaned, store_choices=[])
        if _maybe_request_store_choice(session):
            return None
        _advance(session, DealReportSession.Steps.PRODUCT)
        return None

    return _("Please reply with the number from the list or describe the branch/address.")


def _handle_product(session: DealReportSession, text: str) -> None:
    _update_data(session, product_name=text, product_brand="")
    _advance(session)


def _handle_brand(session: DealReportSession, text: str) -> None:
    cleaned = text.strip()
    lower = cleaned.lower()
    if not cleaned or lower in BRAND_SKIP_KEYWORDS or lower in NO_KEYWORDS:
        _update_data(session, product_brand="")
    else:
        _update_data(session, product_brand=cleaned)
    _advance(session)


def _handle_price(session: DealReportSession, text: str) -> str | None:
    cleaned = text.replace(",", ".")
    try:
        value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return _("Please send the price as digits, e.g., 4.90")
    if value <= 0:
        return _("Price must be greater than zero.")
    _update_data(session, price=str(value.quantize(Decimal("0.01"))))
    _advance(session)
    return None


def _handle_units(session: DealReportSession, text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        units = 1
    else:
        if not cleaned.isdigit():
            return _("Please reply with a whole number, e.g., 1 or 3.")
        units = int(cleaned)
        if units <= 0:
            return _("Number of units must be at least 1.")
    _update_data(session, units_in_price=units)
    _advance(session, DealReportSession.Steps.CLUB)
    return None


def _handle_unit_type(session: DealReportSession, text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return _("Please specify the unit type (e.g., liter, kilogram, pack).")
    translation = resolve_unit_translation(cleaned)
    _update_data(
        session,
        unit_type=translation["en"] or cleaned,
        unit_type_en=translation["en"] or cleaned,
        unit_type_he=translation["he"] or cleaned,
        unit_type_slug=translation["slug"],
    )
    _advance(session, DealReportSession.Steps.UNIT_QUANTITY)
    return None


def _handle_unit_quantity(session: DealReportSession, text: str) -> str | None:
    cleaned = text.replace(",", ".").strip()
    try:
        quantity = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return _("Please reply with a numeric quantity (e.g., 1, 1.5, 2).")
    if quantity <= 0:
        return _("Quantity must be greater than zero.")
    _update_data(session, unit_quantity=str(quantity.quantize(Decimal("0.01"))))
    _advance(session, DealReportSession.Steps.PRICE)
    return None


def _handle_club(session: DealReportSession, text: str) -> str | None:
    lower = text.lower()
    if lower in YES_KEYWORDS:
        _update_data(session, club_only=True)
    elif lower in NO_KEYWORDS:
        _update_data(session, club_only=False)
    else:
        return _("Please reply “yes” or “no”.")
    _advance(session)
    return None


def _handle_limit(session: DealReportSession, text: str) -> str | None:
    lower = text.lower()
    if lower in NO_KEYWORDS or not text.strip():
        _update_data(session, limit_qty=None)
    else:
        if not text.strip().isdigit():
            return _("Please reply with a number (e.g., 2) or “no”.")
        qty = int(text.strip())
        if qty <= 0:
            return _("Limit must be at least 1, or reply “no”.")
        _update_data(session, limit_qty=qty)
    _advance(session)
    return None


def _handle_cart(session: DealReportSession, text: str) -> str | None:
    lower = text.lower()
    if lower in NO_KEYWORDS or not text.strip():
        _update_data(session, min_cart_total=None)
    else:
        cleaned = text.replace(",", ".")
        try:
            value = Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return _("Please send the amount as digits, e.g., 100 or 150.5")
        if value <= 0:
            return _("Cart total must be greater than zero, or reply “no”.")
        _update_data(session, min_cart_total=str(value.quantize(Decimal("0.01"))))
    _advance(session)
    return None


def _handle_default_city_confirm(session: DealReportSession, text: str) -> str | None:
    lower = text.strip().lower()
    data = session.data or {}
    locale = session.user.locale or "he"
    city_value = _format_city_value(data, locale)
def _format_summary(data: dict, locale: str) -> str:
    with translation.override(locale):
        city_value = _format_city_value(data, locale)
        lines = [
            _("Store: %(value)s") % {"value": data.get("store_name", "—")},
            _("City: %(value)s") % {"value": city_value},
            _("Product: %(value)s") % {"value": data.get("product_name", "—")},
        ]
        branch_value = data.get("store_detail")
        if branch_value:
            lines.insert(1, _("Branch or address: %(value)s") % {"value": branch_value})
        brand_value = data.get("product_brand")
        if brand_value:
            lines.append(_("Brand: %(value)s") % {"value": brand_value})
        price = data.get("price")
        if price:
            units = data.get("units_in_price") or 1
            lines.append(_("Price: %(price)s (%(units)s unit(s))") % {"price": price, "units": units})
        unit_label = select_unit_for_locale(data, locale)
        unit_qty = data.get("unit_quantity")
        if unit_label and unit_qty:
            lines.append(_("Package size: %(qty)s %(unit)s") % {"qty": unit_qty, "unit": unit_label})
        club = data.get("club_only")
        if club is True:
            lines.append(_("Club members only: yes"))
        elif club is False:
            lines.append(_("Club members only: no"))
        limit = data.get("limit_qty")
        if limit:
            lines.append(_("Quantity limit: %(limit)s") % {"limit": limit})
        min_cart = data.get("min_cart_total")
        if min_cart:
            lines.append(_("Minimum cart: %(amount)s") % {"amount": min_cart})
        summary = "\n".join(lines)
        closing = _(
            "Thanks! We'll review this deal and let everyone know. "
            "Tap “Add a deal” to share another price, or “Find a deal” to see recent reports."
        )
        moderation = _("Status: awaiting moderation")
        gratitude = _("Thank you for helping the community save together!")
        return f"{summary}\n\n{moderation}\n\n{closing}\n{gratitude}"


def _format_city_value(data: dict, locale: str) -> str:
    city_obj = _city_from_session(data)
    if city_obj:
        primary = city_obj.name_en if locale.startswith("en") else city_obj.name_he
        secondary = city_obj.name_he if locale.startswith("en") else city_obj.name_en
        if secondary and secondary != primary:
            return f"{primary} / {secondary}"
        return primary or secondary or city_obj.display_name
    city_he = data.get("city_he")
    city_en = data.get("city_en")
    fallback = data.get("city")
    primary = city_en if locale.startswith("en") else city_he
    secondary = city_he if locale.startswith("en") else city_en
    if not primary:
        primary = secondary or fallback or "—"
        secondary = city_en if locale.startswith("en") else city_he
    if secondary and secondary != primary:
        return f"{primary} / {secondary}"
    return primary or secondary or fallback or "—"


_STEP_HANDLERS = {
    DealReportSession.Steps.STORE: _handle_store,
    DealReportSession.Steps.BRANCH: _handle_branch,
    DealReportSession.Steps.CITY: _handle_city,
    DealReportSession.Steps.STORE_CONFIRM: _handle_store_confirm,
    DealReportSession.Steps.PRODUCT: _handle_product,
    DealReportSession.Steps.BRAND: _handle_brand,
    DealReportSession.Steps.PRICE: _handle_price,
    DealReportSession.Steps.UNITS: _handle_units,
    DealReportSession.Steps.UNIT_TYPE: _handle_unit_type,
    DealReportSession.Steps.UNIT_QUANTITY: _handle_unit_quantity,
    DealReportSession.Steps.CLUB: _handle_club,
    DealReportSession.Steps.LIMIT: _handle_limit,
    DealReportSession.Steps.CART: _handle_cart,
}


def _persist_price_report(session: DealReportSession, user: WAUser) -> Optional[PriceReport]:
    data = session.data or {}
    if data.get("price_report_id"):
        return PriceReport.objects.filter(pk=data["price_report_id"]).first()

    price_raw = data.get("price")
    if not price_raw:
        return None
    try:
        price_value = Decimal(price_raw).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None

    store = _get_or_create_store(data)
    product = _get_or_create_product(data)
    observed_at = timezone.now()
    min_cart = data.get("min_cart_total")
    if min_cart:
        try:
            min_cart_decimal = Decimal(min_cart).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError):
            min_cart_decimal = None
    else:
        min_cart_decimal = None

    limit_qty = data.get("limit_qty")
    deal_notes = _build_deal_notes(limit_qty)

    unit_type = data.get("unit_type")
    unit_quantity = data.get("unit_quantity")
    unit_type_he = data.get("unit_type_he") or (unit_type if unit_type and _contains_hebrew(unit_type) else "")
    unit_type_en = data.get("unit_type_en") or (unit_type if unit_type and not _contains_hebrew(unit_type) else "")
    if product:
        unit_type = unit_type or product.default_unit_type_en or product.default_unit_type
        if not unit_type_he:
            unit_type_he = product.default_unit_type_he or unit_type_he
        if not unit_type_en:
            unit_type_en = product.default_unit_type_en or unit_type_en or unit_type
        unit_quantity = unit_quantity or (
            str(product.default_unit_quantity) if product.default_unit_quantity else None
        )

    price_report = PriceReport.objects.create(
        user=user,
        product=product,
        store=store,
        price=price_value,
        units_in_price=int(data.get("units_in_price") or 1),
        is_for_club_members_only=bool(data.get("club_only")),
        min_cart_total=min_cart_decimal,
        unit_measure_type=unit_type_en or unit_type or "",
        unit_measure_type_he=unit_type_he or unit_type_en or unit_type or "",
        unit_measure_type_en=unit_type_en or unit_type_he or unit_type or "",
        unit_measure_quantity=Decimal(unit_quantity) if unit_quantity else None,
        deal_notes=deal_notes,
        observed_at=observed_at,
        product_text_raw=data.get("product_name", ""),
        locale=getattr(user, "locale", "en"),
        source="whatsapp",
        needs_moderation=True,
    )
    data["price_report_id"] = price_report.id
    session.data = data
    session.save(update_fields=["data"])

    if product:
        updated = False
        fields_to_update = []
        if unit_type_en and not product.default_unit_type_en:
            product.default_unit_type_en = unit_type_en
            product.default_unit_type = unit_type_en
            updated = True
            fields_to_update.extend(["default_unit_type_en", "default_unit_type"])
        if unit_type_he and not product.default_unit_type_he:
            product.default_unit_type_he = unit_type_he
            updated = True
            fields_to_update.append("default_unit_type_he")
        if unit_quantity and not product.default_unit_quantity:
            product.default_unit_quantity = Decimal(unit_quantity)
            updated = True
            fields_to_update.append("default_unit_quantity")
        if updated:
            product.save(update_fields=list(set(fields_to_update)))
    return price_report


def _normalize_text(value: str) -> str:
    return (value or "").strip()


def _get_or_create_store(data: dict) -> Store:
    store_id = data.get("store_id")
    if store_id:
        store = Store.objects.filter(pk=store_id).first()
        if store:
            return store
    name = _normalize_text(data.get("store_name")) or "Unknown store"
    city_he = _normalize_text(data.get("city_he"))
    city_en = _normalize_text(data.get("city_en"))
    city = _normalize_text(data.get("city")) or city_en or city_he
    detail = _normalize_text(data.get("store_detail"))
    city_obj = _city_from_session(data) or _match_city(city) or _match_city(city_he) or _match_city(city_en)
    city_id = str(city_obj.id) if city_obj else None
    store = _match_store(name, city_he, city_en, detail, city_id)
    if store:
        return store
    display_name = f"{name} - {detail}" if detail else name
    city_he_value = city_he if city_he else (city if _contains_hebrew(city) else "")
    city_en_value = city_en if city_en else (city if _contains_latin(city) else "")
    if city_obj is None and (city_he_value or city_en_value or city):
        city_obj = City.objects.create(
            name_he=city_he_value or city or city_en_value,
            name_en=city_en_value or city or city_he_value,
        )
    return Store.objects.create(
        name=name,
        display_name=display_name,
        city=city or "",
        city_he=city_he_value,
        city_en=city_en_value,
        city_obj=city_obj,
        address=data.get("store_detail") or "",
    )


def _match_store(
    name: str,
    city_he: Optional[str] = None,
    city_en: Optional[str] = None,
    detail: Optional[str] = None,
    city_id: Optional[str] = None,
) -> Store | None:
    qs = Store.objects.all()
    city_values = [value for value in (_normalize_text(city_he), _normalize_text(city_en)) if value]
    city_filter = _build_city_filter(city_values) if city_values else None
    if city_id:
        qs = qs.filter(city_obj_id=city_id)
    elif city_filter:
        qs = qs.filter(city_filter)
    normalized_name = normalize_store_text(name)
    base_filter = Q(name__iexact=name) | Q(display_name__iexact=name)
    if normalized_name:
        base_filter |= Q(name_search_terms__contains=[normalized_name])
    matches = qs.filter(base_filter)
    if detail:
        detail_filter = (
            Q(display_name__icontains=detail)
            | Q(name__icontains=detail)
            | Q(address__icontains=detail)
        )
        detailed = matches.filter(detail_filter)
        if detailed.exists():
            return detailed.first()
    store = matches.first()
    if store:
        return store
    chunks = _chunk_variants(name)
    if chunks:
        partial_filter = Q()
        for chunk in chunks:
            partial_filter |= Q(name__icontains=chunk) | Q(display_name__icontains=chunk)
        qs_partial = Store.objects.filter(partial_filter)
        if city_filter:
            qs_partial = qs_partial.filter(city_filter)
        return qs_partial.first()
    return None


def _find_store_candidates(name: str, data: dict) -> list[Store]:
    base_qs = Store.objects.filter(is_active=True)
    city_values = _city_query_values(data)
    city_id = data.get("city_id")
    if city_id:
        base_qs = base_qs.filter(city_obj_id=city_id)
    elif city_values:
        base_qs = base_qs.filter(_build_city_filter(city_values))

    normalized_name = normalize_store_text(name)
    base_filter = Q(name__iexact=name) | Q(display_name__iexact=name)
    if normalized_name:
        base_filter |= Q(name_search_terms__contains=[normalized_name])
    exact_qs = base_qs.filter(base_filter)

    detail = _normalize_text(data.get("store_detail"))
    if detail and exact_qs.exists():
        detail_filter = (
            Q(display_name__icontains=detail)
            | Q(name__icontains=detail)
            | Q(address__icontains=detail)
        )
        narrowed = exact_qs.filter(detail_filter)
        if narrowed.exists():
            exact_qs = narrowed

    candidates: list[Store] = []
    added_ids: set[int] = set()
    for store in exact_qs:
        candidates.append(store)
        added_ids.add(store.id)
        if len(candidates) >= MAX_STORE_CHOICES:
            return candidates

    chunks = _chunk_variants(name)
    if chunks:
        partial_filter = Q()
        for chunk in chunks:
            partial_filter |= Q(name__icontains=chunk) | Q(display_name__icontains=chunk)
        partial_qs = base_qs.filter(partial_filter)
        for store in partial_qs:
            if store.id in added_ids:
                continue
            candidates.append(store)
            added_ids.add(store.id)
            if len(candidates) >= MAX_STORE_CHOICES:
                break

    return candidates


def _chunk_variants(value: str) -> set[str]:
    if not value:
        return set()
    chunk = value[:3] if len(value) >= 3 else value
    variants = {chunk} if chunk else set()
    for source, target in HEBREW_DOUBLE_FORMS:
        next_variants = set(variants)
        for option in variants:
            if source in option:
                next_variants.add(option.replace(source, target))
        variants = next_variants
    return {variant for variant in variants if variant}


def _match_city(name: Optional[str]) -> Optional[City]:
    value = _normalize_text(name)
    if not value:
        return None
    return City.objects.filter(Q(name_he__iexact=value) | Q(name_en__iexact=value)).first()


def _get_or_create_product(data: dict) -> Product:
    name = _normalize_text(data.get("product_name")) or "Unknown product"
    brand = _normalize_text(data.get("product_brand"))
    product = _match_product(name, brand)
    if product:
        if brand and not product.brand:
            product.brand = brand
            product.save(update_fields=["brand"])
        return product
    return Product.objects.create(
        name_he=name,
        name_en=name,
        brand=brand or "",
        variant="",
    )


def _match_product(name: str, brand: Optional[str] = None) -> Product | None:
    if brand:
        product = Product.objects.filter(name_he__iexact=name, brand__iexact=brand).first()
        if product:
            return product
        product = Product.objects.filter(name_en__iexact=name, brand__iexact=brand).first()
        if product:
            return product

    product = Product.objects.filter(name_he__iexact=name).first()
    if product:
        return product
    product = Product.objects.filter(name_en__iexact=name).first()
    if product:
        return product

    prefix = name[:3]
    if len(prefix) >= 3:
        qs = Product.objects.filter(name_he__icontains=prefix)
        if brand:
            branded = qs.filter(brand__iexact=brand).first()
            if branded:
                return branded
        product = qs.first()
        if product:
            return product
    return None


def _build_deal_notes(limit_qty) -> str:
    notes = []
    if limit_qty:
        notes.append(_("Limit per shopper: %(limit)s") % {"limit": limit_qty})
    return "; ".join(notes)[:240]
