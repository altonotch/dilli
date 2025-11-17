from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from catalog.models import Product
from stores.models import Store, City
from pricing.models import PriceReport
from whatsapp.models import WAUser, DealLookupSession
from whatsapp.search_flow import start_find_deal_flow, handle_find_deal_text


class SearchFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = WAUser.objects.create(wa_id_hash="hash", locale="en")
        self.city = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        self.other_city = City.objects.create(name_he="חיפה", name_en="Haifa")
        self.store_primary = Store.objects.create(
            name="Shufersal Center",
            display_name="Shufersal Center",
            city="Tel Aviv",
            city_obj=self.city,
        )
        self.store_secondary = Store.objects.create(
            name="City Super",
            display_name="City Super",
            city="Tel Aviv",
            city_obj=self.city,
        )
        self.store_other_brand = Store.objects.create(
            name="Strauss Shop",
            display_name="Strauss Shop",
            city="Tel Aviv",
            city_obj=self.city,
        )
        self.store_other_city = Store.objects.create(
            name="Haifa Fresh",
            display_name="Haifa Fresh",
            city="Haifa",
            city_obj=self.other_city,
        )
        self.product_tnuva = Product.objects.create(
            name_he="חלב תנובה 3%",
            name_en="Tnuva Milk 3%",
            brand="Tnuva",
        )
        self.product_strauss = Product.objects.create(
            name_he="חלב שטראוס 3%",
            name_en="Strauss Milk 3%",
            brand="Strauss",
        )
        now = timezone.now()
        PriceReport.objects.create(
            user=self.user,
            product=self.product_tnuva,
            store=self.store_primary,
            price="5.90",
            units_in_price=1,
            observed_at=now,
            needs_moderation=False,
            product_text_raw="Tnuva Milk 3%",
        )
        PriceReport.objects.create(
            user=self.user,
            product=self.product_tnuva,
            store=self.store_primary,
            price="4.10",
            units_in_price=1,
            observed_at=now - timedelta(days=3),
            needs_moderation=False,
            product_text_raw="Tnuva Milk 3%",
        )
        PriceReport.objects.create(
            user=self.user,
            product=self.product_tnuva,
            store=self.store_secondary,
            price="6.20",
            units_in_price=1,
            observed_at=now - timedelta(hours=2),
            needs_moderation=False,
            product_text_raw="Tnuva Milk 3%",
        )
        PriceReport.objects.create(
            user=self.user,
            product=self.product_strauss,
            store=self.store_other_brand,
            price="4.50",
            units_in_price=1,
            observed_at=now - timedelta(hours=1),
            needs_moderation=False,
            product_text_raw="Strauss Milk 3%",
        )
        PriceReport.objects.create(
            user=self.user,
            product=self.product_tnuva,
            store=self.store_other_city,
            price="6.80",
            units_in_price=1,
            observed_at=now - timedelta(hours=1),
            needs_moderation=False,
            product_text_raw="Tnuva Milk 3%",
        )

    def test_flow_collects_product_brand_city_and_returns_latest_result_per_store(self):
        locale = "en"
        prompt = start_find_deal_flow(self.user, locale)
        self.assertIn("which product", prompt.lower())

        brand_prompt = handle_find_deal_text(self.user, locale, "Milk 3%")
        self.assertIn("brand", brand_prompt.lower())

        city_prompt = handle_find_deal_text(self.user, locale, "tnuva")
        self.assertIn("city", city_prompt.lower())

        results = handle_find_deal_text(self.user, locale, "Tel Aviv")
        self.assertIn("Shufersal Center", results)
        self.assertIn("City Super", results)
        self.assertNotIn("Strauss Shop", results)
        self.assertNotIn("Haifa Fresh", results)
        self.assertIn("5.90", results)
        self.assertNotIn("4.10", results)
        self.assertEqual(results.count("Shufersal Center"), 1)
        self.assertEqual(results.count("City Super"), 1)

        session = DealLookupSession.objects.get(user=self.user)
        self.assertFalse(session.is_active)
        self.assertEqual(session.step, DealLookupSession.Steps.COMPLETE)

    def test_flow_respects_hebrew_locale_queries(self):
        user = WAUser.objects.create(wa_id_hash="hash2", locale="he")
        start_find_deal_flow(user, "he")
        handle_find_deal_text(user, "he", "חלב")
        handle_find_deal_text(user, "he", "תנובה")
        results = handle_find_deal_text(user, "he", "תל אביב")
        self.assertIn("Shufersal Center", results)
        self.assertIn("5.90", results)

    def test_flow_handles_no_results(self):
        locale = "en"
        start_find_deal_flow(self.user, locale)
        handle_find_deal_text(self.user, locale, "Nonexistent")
        handle_find_deal_text(self.user, locale, "unknown")
        response = handle_find_deal_text(self.user, locale, "Tel Aviv")
        self.assertIn("couldn't find", response.lower())
