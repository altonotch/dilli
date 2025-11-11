from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db.models import Q
from django.utils import translation
from django.utils.translation import gettext as _

from pricing.models import PriceReport
from stores.models import Store
from .models import DealLookupSession, WAUser


SEARCH_RADIUS_KM = 3


def start_find_deal_flow(user: WAUser, locale: str) -> str:
    DealLookupSession.objects.filter(user=user, is_active=True).update(is_active=False, step=DealLookupSession.Steps.CANCELED)
    session = DealLookupSession.objects.create(user=user)
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
            session.step = DealLookupSession.Steps.LOCATION
            session.save(update_fields=["data", "step", "updated_at"])
            return _question(session.step, locale)
        elif session.step == DealLookupSession.Steps.LOCATION:
            session.data = {**(session.data or {}), "city": text}
            session.step = DealLookupSession.Steps.COMPLETE
            session.is_active = False
            session.save(update_fields=["data", "step", "is_active", "updated_at"])
            return _format_results(session, locale)
    return None


def handle_find_deal_location(user: WAUser, locale: str, location_payload: dict) -> Optional[str]:
    session = _get_active_session(user)
    if not session or session.step != DealLookupSession.Steps.LOCATION:
        return None
    lat = location_payload.get("latitude")
    lon = location_payload.get("longitude")
    if lat is None or lon is None:
        return None
    session.data = {**(session.data or {}), "latitude": float(lat), "longitude": float(lon)}
    session.step = DealLookupSession.Steps.COMPLETE
    session.is_active = False
    session.save(update_fields=["data", "step", "is_active", "updated_at"])
    with translation.override(locale):
        return _format_results(session, locale)


def _get_active_session(user: WAUser) -> Optional[DealLookupSession]:
    return DealLookupSession.objects.filter(user=user, is_active=True).order_by("-updated_at").first()


def _question(step: str, locale: str) -> str:
    with translation.override(locale):
        prompts = {
            DealLookupSession.Steps.PRODUCT: _("Which product are you looking for?"),
            DealLookupSession.Steps.LOCATION: _(
                "Type the city or send your 📍 location so I can find nearby deals."
            ),
        }
        return prompts.get(step, _("Thanks!"))


def _format_results(session: DealLookupSession, locale: str) -> str:
    data = session.data or {}
    product_query = data.get("product_query")
    if not product_query:
        with translation.override(locale):
            return _("Please start again and tell me which product you want.")

    deals = _fetch_deals(product_query, data)
    with translation.override(locale):
        if not deals:
            return _("Sorry, I couldn't find any recent deals for %(product)s." % {"product": product_query})
        lines = [_("Here are the latest deals:")]
        for deal in deals:
            line = _("• %(product)s — %(price)s₪ at %(store)s (%(city)s)") % {
                "product": deal.product_name,
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
    price: str
    store_name: str
    city: Optional[str]


def _fetch_deals(product_query: str, data: dict, limit: int = 3) -> list[DealResult]:
    qs = PriceReport.objects.filter(needs_moderation=False).select_related("product", "store").order_by("-observed_at")
    qs = qs.filter(
        Q(product__name_he__icontains=product_query)
        | Q(product__name_en__icontains=product_query)
        | Q(product_text_raw__icontains=product_query)
    )

    city = data.get("city")
    if city:
        qs = qs.filter(
            Q(store__city__iexact=city)
            | Q(store__city_he__iexact=city)
            | Q(store__city_en__iexact=city)
            | Q(store__city_obj__name_he__iexact=city)
            | Q(store__city_obj__name_en__iexact=city)
        )

    lat = data.get("latitude")
    lon = data.get("longitude")
    if lat is not None and lon is not None:
        point = Point(float(lon), float(lat), srid=4326)
        qs = qs.filter(store__location__isnull=False, store__location__distance_lte=(point, SEARCH_RADIUS_KM * 1000))
        qs = qs.annotate(distance=Distance("store__location", point)).order_by("distance")

    results = []
    for report in qs[:limit]:
        results.append(
            DealResult(
                product_name=report.product_text_raw or report.product.name_he,
                price=str(report.price),
                store_name=report.store.display_name or report.store.name,
                city=_store_city_display(report.store),
            )
        )
    return results


def _store_city_display(store: Store) -> str:
    if store.city_obj:
        return store.city_obj.display_name
    return store.city or store.city_en or store.city_he or ""
