from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Optional
import logging

from django.utils import translation, timezone
from django.utils.translation import gettext as _

from catalog.models import Product
from stores.models import Store
from pricing.models import PriceReport

from .models import DealReportSession, WAUser

QUESTION_SEQUENCE = [
    DealReportSession.Steps.STORE,
    DealReportSession.Steps.CITY,
    DealReportSession.Steps.PRODUCT,
    DealReportSession.Steps.PRICE,
    DealReportSession.Steps.UNITS,
    DealReportSession.Steps.CLUB,
    DealReportSession.Steps.LIMIT,
    DealReportSession.Steps.CART,
]

logger = logging.getLogger(__name__)

CANCEL_KEYWORDS = {"cancel", "stop", "בטל", "ביטול", "סיים", "סיום"}
YES_KEYWORDS = {"yes", "y", "yeah", "כן", "yep", "si"}
NO_KEYWORDS = {"no", "n", "not", "לא", "nope", "אין"}


def start_add_deal_flow(user: WAUser, locale: str) -> str:
    DealReportSession.objects.filter(user=user, is_active=True).update(
        is_active=False, step=DealReportSession.Steps.CANCELED
    )
    session = DealReportSession.objects.create(user=user)
    return _question_text(session.step, locale)


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

        # If handler returned None, we already advanced and should ask next question
        if session.step in QUESTION_SEQUENCE:
            return _question_text(session.step, locale)
        else:
            summary = _format_summary(session.data, locale)
            try:
                _persist_price_report(session, user)
            except Exception:
                logger.exception("Failed to persist deal session %s", session.pk)
            return summary


def _question_text(step: str, locale: str) -> str:
    with translation.override(locale):
        prompts = {
            DealReportSession.Steps.STORE: _(
                "Which store or branch is this deal from?\nExample: “Shufersal Givat Tal”."
            ),
            DealReportSession.Steps.CITY: _(
                "Which city is the store in?"
            ),
            DealReportSession.Steps.PRODUCT: _(
                "What product is this? Include brand and size if possible."
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
        return prompts.get(step, _("Thanks!"))


def _advance(session: DealReportSession) -> None:
    try:
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
    _update_data(session, store_name=text)
    _advance(session)


def _handle_city(session: DealReportSession, text: str) -> None:
    _update_data(session, city=text)
    _advance(session)


def _handle_product(session: DealReportSession, text: str) -> None:
    _update_data(session, product_name=text)
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
    _advance(session)
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


def _format_summary(data: dict, locale: str) -> str:
    with translation.override(locale):
        lines = [
            _("Store: %(value)s") % {"value": data.get("store_name", "—")},
            _("City: %(value)s") % {"value": data.get("city", "—")},
            _("Product: %(value)s") % {"value": data.get("product_name", "—")},
        ]
        price = data.get("price")
        if price:
            units = data.get("units_in_price") or 1
            lines.append(_("Price: %(price)s (%(units)s unit(s))") % {"price": price, "units": units})
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
            "You can tap “Add a deal” to share another one."
        )
        moderation = _("Status: awaiting moderation")
        gratitude = _("Thank you for helping the community save together!")
        return f"{summary}\n\n{moderation}\n\n{closing}\n{gratitude}"


_STEP_HANDLERS = {
    DealReportSession.Steps.STORE: _handle_store,
    DealReportSession.Steps.CITY: _handle_city,
    DealReportSession.Steps.PRODUCT: _handle_product,
    DealReportSession.Steps.PRICE: _handle_price,
    DealReportSession.Steps.UNITS: _handle_units,
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

    price_report = PriceReport.objects.create(
        user=user,
        product=product,
        store=store,
        price=price_value,
        units_in_price=int(data.get("units_in_price") or 1),
        is_for_club_members_only=bool(data.get("club_only")),
        min_cart_total=min_cart_decimal,
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
    return price_report


def _normalize_text(value: str) -> str:
    return (value or "").strip()


def _get_or_create_store(data: dict) -> Store:
    name = _normalize_text(data.get("store_name")) or "Unknown store"
    city = _normalize_text(data.get("city"))
    store = _match_store(name, city)
    if store:
        return store
    return Store.objects.create(
        name=name,
        display_name=name,
        city=city,
    )


def _match_store(name: str, city: str) -> Store | None:
    qs = Store.objects.all()
    if city:
        qs = qs.filter(city__iexact=city)
    candidates = qs.filter(name__iexact=name)
    store = candidates.first()
    if store:
        return store
    if len(name) >= 3:
        partial = qs.filter(name__icontains=name[:3])
        return partial.first()
    return None


def _get_or_create_product(data: dict) -> Product:
    name = _normalize_text(data.get("product_name")) or "Unknown product"
    product = _match_product(name)
    if product:
        return product
    return Product.objects.create(
        name_he=name,
        name_en=name,
        brand="",
        variant="",
    )


def _match_product(name: str) -> Product | None:
    product = Product.objects.filter(name_he__iexact=name).first()
    if product:
        return product
    product = Product.objects.filter(name_en__iexact=name).first()
    if product:
        return product
    if len(name) >= 3:
        return Product.objects.filter(name_he__icontains=name[:3]).first()
    return None


def _build_deal_notes(limit_qty) -> str:
    notes = []
    if limit_qty:
        notes.append(_("Limit per shopper: %(limit)s") % {"limit": limit_qty})
    return "; ".join(notes)[:240]
