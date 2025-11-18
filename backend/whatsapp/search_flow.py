from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from django.db.models import Q
from django.utils import translation
from django.utils.translation import gettext as _
import structlog

from pricing.models import PriceReport
from stores.models import Store
from .deal_flow import BRAND_SKIP_KEYWORDS
from .models import DealLookupSession, WAUser


RESULT_LIMIT = 5

logger = structlog.get_logger(__name__)


def start_find_deal_flow(user: WAUser, locale: str) -> str:
    DealLookupSession.objects.filter(user=user, is_active=True).update(is_active=False, step=DealLookupSession.Steps.CANCELED)
    session = DealLookupSession.objects.create(user=user)
    logger.info("Started find-deal flow session=%s user=%s", session.pk, user.pk)
    return _question(session.step, locale)


def handle_find_deal_text(user: WAUser, locale: str, message_text: Optional[str]) -> Optional[str]:
    session = _get_active_session(user)
    if not session or session.step == DealLookupSession.Steps.COMPLETE:
        return None
    text = (message_text or "").strip()
    if not text:
        return None

    with translation.override(locale):
        if session.step == DealLookupSession.Steps.PRODUCT:
            session.data = {**(session.data or {}), "product_query": text}
            session.step = DealLookupSession.Steps.BRAND
            session.save(update_fields=["data", "step", "updated_at"])
            logger.info(
                "Captured product query for find-deal session=%s user=%s query=%s",
                session.pk,
                user.pk,
                text[:80],
            )
            return _question(session.step, locale)
        if session.step == DealLookupSession.Steps.BRAND:
            normalized = text.lower()
            brand_value = None if normalized in BRAND_SKIP_KEYWORDS else text
            session.data = {**(session.data or {}), "brand_query": brand_value}
            session.step = DealLookupSession.Steps.LOCATION
            session.save(update_fields=["data", "step", "updated_at"])
            logger.info(
                "Captured brand query for find-deal session=%s user=%s brand=%s",
                session.pk,
                user.pk,
                (brand_value or "any")[:80],
            )
            return _question(session.step, locale)
        if session.step == DealLookupSession.Steps.LOCATION:
            session.data = {**(session.data or {}), "city": text}
            session.step = DealLookupSession.Steps.COMPLETE
            session.is_active = False
            session.save(update_fields=["data", "step", "is_active", "updated_at"])
            logger.info(
                "Captured city query for find-deal session=%s user=%s city=%s",
                session.pk,
                user.pk,
                text[:80],
            )
            return _format_results(session, locale)
    return None


def handle_find_deal_location(user: WAUser, locale: str, location_payload: dict) -> Optional[str]:
    session = _get_active_session(user)
    if not session or session.step != DealLookupSession.Steps.LOCATION:
        return None
    logger.info(
        "Received location payload for find-deal session=%s user=%s lat=%s lon=%s",
        session.pk,
        user.pk,
        location_payload.get("latitude"),
        location_payload.get("longitude"),
    )
    with translation.override(locale):
        return _("Please type the city name so I can find the right deals.")


def _get_active_session(user: WAUser) -> Optional[DealLookupSession]:
    return DealLookupSession.objects.filter(user=user, is_active=True).order_by("-updated_at").first()


def _question(step: str, locale: str) -> str:
    with translation.override(locale):
        prompts = {
            DealLookupSession.Steps.PRODUCT: _("Which product are you looking for?"),
            DealLookupSession.Steps.BRAND: _(
                "Which brand do you prefer for this product? Type \"skip\" if you don't mind."
            ),
            DealLookupSession.Steps.LOCATION: _(
                "Which city should I search in?"
            ),
        }
        return prompts.get(step, _("Thanks!"))


def _format_results(session: DealLookupSession, locale: str) -> str:
    data = session.data or {}
    product_query = data.get("product_query")
    brand_query = data.get("brand_query")
    city_query = data.get("city")
    if not product_query:
        with translation.override(locale):
            return _("Please start again and tell me which product you want.")
    if not city_query:
        with translation.override(locale):
            return _("Please start again and tell me which city you want.")

    deals = _fetch_deals(product_query, brand_query, city_query, locale)
    logger.info(
        "Formatted find-deal results session=%s user=%s product=%s brand=%s city=%s count=%s",
        session.pk,
        session.user_id,
        product_query,
        brand_query or "any",
        city_query,
        len(deals),
    )
    with translation.override(locale):
        if not deals:
            return _(
                "Sorry, I couldn't find any recent deals for %(product)s in %(city)s."
                % {"product": product_query, "city": city_query}
            )
        lines = [_("Here are the latest deals:")]
        for deal in deals:
            brand_part = _(" (%(brand)s)") % {"brand": deal.brand} if deal.brand else ""
            line = _("• %(product)s%(brand)s — %(price)s₪ at %(store)s (%(city)s)") % {
                "product": deal.product_name,
                "brand": brand_part,
                "price": deal.price,
                "store": deal.store_name,
                "city": deal.city or "",
            }
            lines.append(line)
        lines.append(_("Tip: tap “Add a deal” to share your own find."))
        return "\n".join(lines)


@dataclass
class DealResult:
    product_name: str
    brand: Optional[str]
    price: str
    store_name: str
    city: Optional[str]


def _fetch_deals(
    product_query: str,
    brand_query: Optional[str],
    city_query: str,
    locale: str,
    limit: int = RESULT_LIMIT,
) -> list[DealResult]:
    qs = (
        PriceReport.objects.filter(needs_moderation=False)
        .select_related("product", "store", "store__city_obj")
        .order_by("-observed_at")
    )
    qs = qs.filter(_product_filter_for_locale(product_query, locale))
    qs = qs.filter(_city_filter(city_query))
    if brand_query:
        qs = qs.filter(_brand_filter(brand_query))

    seen: set[tuple[int, int, str]] = set()
    results: list[DealResult] = []
    lang = _lang(locale)

    for report in qs:
        brand = (report.product.brand or "").strip()
        dedupe_key = (report.store_id, report.product_id, brand.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        product_name = _result_product_name(report, lang)
        results.append(
            DealResult(
                product_name=product_name,
                brand=brand or None,
                price=str(report.price),
                store_name=report.store.display_name or report.store.name,
                city=_store_city_display(report.store),
            )
        )
        if len(results) >= limit:
            break
    return results


def _store_city_display(store: Store) -> str:
    if store.city_obj:
        return store.city_obj.display_name
    return store.city or store.city_en or store.city_he or ""


def _product_filter_for_locale(product_query: str, locale: str) -> Q:
    lang = _lang(locale)
    if lang == "he":
        base = Q(product__name_he__icontains=product_query)
    else:
        base = Q(product__name_en__icontains=product_query)
    return base | Q(product_text_raw__icontains=product_query)


def _brand_filter(brand_query: str) -> Q:
    return (
        Q(product__brand__icontains=brand_query)
        | Q(product__name_he__icontains=brand_query)
        | Q(product__name_en__icontains=brand_query)
        | Q(product_text_raw__icontains=brand_query)
    )


def _city_filter(city_query: str) -> Q:
    city = (city_query or "").strip()
    if not city:
        return Q()
    return (
        Q(store__city__iexact=city)
        | Q(store__city_he__iexact=city)
        | Q(store__city_en__iexact=city)
        | Q(store__city_obj__name_he__iexact=city)
        | Q(store__city_obj__name_en__iexact=city)
    )


def _result_product_name(report: PriceReport, lang: str) -> str:
    if report.product_text_raw:
        return report.product_text_raw
    if lang == "he":
        return report.product.name_he or report.product.name_en
    return report.product.name_en or report.product.name_he


def _lang(locale: str) -> str:
    return "he" if (locale or "").lower().startswith("he") else "en"
