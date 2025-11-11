from __future__ import annotations

from django.contrib.gis.geos import Point
from django.test import TestCase

from catalog.models import Product
from stores.models import Store, City
from pricing.models import PriceReport
from whatsapp.models import WAUser
from whatsapp.search_flow import start_find_deal_flow, handle_find_deal_text, handle_find_deal_location


class SearchFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = WAUser.objects.create(wa_id_hash="hash", locale="en")
        self.city = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        self.store = Store.objects.create(
            name="Test Store",
            city="Tel Aviv",
            city_obj=self.city,
            location=Point(34.78, 32.08),
        )
        self.product = Product.objects.create(name_he="Milk", name_en="Milk")
        PriceReport.objects.create(
            user=self.user,
            product=self.product,
            store=self.store,
            price="4.20",
            units_in_price=1,
            observed_at="2025-01-01T00:00:00Z",
            needs_moderation=False,
        )

    def test_find_deal_flow_by_city(self):
        locale = "en"
        prompt = start_find_deal_flow(self.user, locale)
        self.assertIn("which product", prompt.lower())
        next_prompt = handle_find_deal_text(self.user, locale, "Milk")
        self.assertIn("city", next_prompt.lower())
        results = handle_find_deal_text(self.user, locale, "Tel Aviv")
        self.assertIn("latest deals", results.lower())
        self.assertIn("Test Store", results)

    def test_find_deal_flow_by_location(self):
        locale = "en"
        start_find_deal_flow(self.user, locale)
        handle_find_deal_text(self.user, locale, "Milk")
        response = handle_find_deal_location(
            self.user,
            locale,
            {"latitude": 32.08, "longitude": 34.78},
        )
        self.assertIn("latest deals", response.lower())
