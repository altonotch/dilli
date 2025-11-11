from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from stores.models import Store, City
from whatsapp.models import WAUser, DealReportSession
from whatsapp.deal_flow import start_add_deal_flow, handle_deal_flow_response
from pricing.models import PriceReport


class DealFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = WAUser.objects.create(wa_id_hash="hash", locale="en")
        self.city = City.objects.create(name_he="ראש העין", name_en="Rosh HaAyin")

    def test_full_flow_collects_all_answers_and_returns_summary(self):
        locale = "en"
        prompt = start_add_deal_flow(self.user, locale)
        self.assertIn("which store", prompt.lower())

        flow = [
            ("Shufersal Givat Tal", "Which city"),
            ("ראש העין", "What product"),
            ("Milk 3% 1L", "What unit is the package"),
            ("Liter", "How many of that unit"),
            ("1", "What is the price"),
            ("4.90", "How many units"),
            ("2", "Is this deal only for club"),
            ("yes", "Is there a quantity limit"),
            ("3", "Is there a minimum cart"),
        ]

        for answer, expected_prompt in flow:
            response = handle_deal_flow_response(self.user, locale, answer)
            self.assertIn(expected_prompt.lower(), response.lower())

        summary = handle_deal_flow_response(self.user, locale, "100")
        self.assertIn("Shufersal Givat Tal", summary)
        self.assertIn("Rosh HaAyin", summary)
        self.assertIn("ראש העין", summary)
        self.assertIn("Milk 3% 1L", summary)
        self.assertIn("4.90", summary)
        self.assertIn("2 unit", summary)
        self.assertIn("Liter", summary)
        self.assertIn("awaiting moderation", summary.lower())
        session = DealReportSession.objects.filter(user=self.user).latest("updated_at")
        self.assertFalse(session.is_active)
        self.assertEqual(session.step, DealReportSession.Steps.COMPLETE)
        pr = PriceReport.objects.get()
        self.assertEqual(pr.price, Decimal("4.90"))
        self.assertEqual(pr.units_in_price, 2)
        self.assertTrue(pr.is_for_club_members_only)
        self.assertEqual(pr.min_cart_total, Decimal("100.00"))
        self.assertTrue(pr.needs_moderation)
        self.assertIn("Limit per shopper", pr.deal_notes)
        self.assertEqual(pr.product_text_raw, "Milk 3% 1L")
        self.assertEqual(pr.unit_measure_type, "Liter")
        self.assertEqual(pr.unit_measure_quantity, Decimal("1.00"))

    def test_invalid_price_prompts_again(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "Store A")
        product_prompt = handle_deal_flow_response(self.user, locale, "City A")
        self.assertIn("what product", product_prompt.lower())
        handle_deal_flow_response(self.user, locale, "Product A")
        handle_deal_flow_response(self.user, locale, "Bottle")
        handle_deal_flow_response(self.user, locale, "1")

        error = handle_deal_flow_response(self.user, locale, "abc")
        self.assertIn("digits", error.lower())
        self.assertEqual(PriceReport.objects.count(), 0)

        next_prompt = handle_deal_flow_response(self.user, locale, "5.10")
        self.assertIn("how many units", next_prompt.lower())

    def test_cancel_flow_marks_session_inactive(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        cancel_msg = handle_deal_flow_response(self.user, locale, "cancel")
        self.assertIn("canceled", cancel_msg.lower())
        session = DealReportSession.objects.filter(user=self.user).latest("updated_at")
        self.assertFalse(session.is_active)
        self.assertEqual(session.step, DealReportSession.Steps.CANCELED)
        self.assertEqual(PriceReport.objects.count(), 0)

    def test_existing_store_and_product_are_reused(self):
        locale = "en"
        existing_store = Store.objects.create(name="Shufersal Givat Tal", city="Rosh HaAyin", city_obj=self.city)
        existing_product = Product.objects.create(
            name_he="Milk 3% 1L",
            name_en="Milk 3% 1L",
            default_unit_type="Liter",
            default_unit_quantity=Decimal("1.00"),
        )

        start_add_deal_flow(self.user, locale)
        flow_answers = [
            "Shufersal Givat Tal",
            "ראש העין",
            "Milk 3% 1L",
            "Liter",
            "1",
            "4.50",
            "1",
            "no",
            "no",
            "no",
        ]
        summary = None
        for answer in flow_answers:
            summary = handle_deal_flow_response(self.user, locale, answer)

        self.assertIn("Shufersal Givat Tal", summary)
        report = PriceReport.objects.get()
        self.assertEqual(report.store_id, existing_store.id)
        self.assertEqual(report.product_id, existing_product.id)
        self.assertEqual(report.unit_measure_type, "Liter")
        self.assertEqual(report.unit_measure_quantity, Decimal("1.00"))

    def test_city_lookup_populates_bilingual_names_from_city_model(self):
        locale = "en"
        tel_aviv = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "Store Alpha")
        product_prompt = handle_deal_flow_response(self.user, locale, "תל אביב")
        self.assertIn("what product", product_prompt.lower())
        session = DealReportSession.objects.filter(user=self.user).latest("updated_at")
        self.assertEqual(session.data.get("city_he"), "תל אביב")
        self.assertEqual(session.data.get("city_en"), "Tel Aviv")
        self.assertEqual(session.data.get("city_id"), str(tel_aviv.id))

    def test_store_disambiguation_prompts_and_allows_choice(self):
        locale = "en"
        tel_aviv = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        Store.objects.create(
            name="Shufersal",
            display_name="Shufersal Center",
            city="Tel Aviv",
            address="Dizengoff 50",
            city_obj=tel_aviv,
        )
        target = Store.objects.create(
            name="Shufersal",
            display_name="Shufersal North",
            city="Tel Aviv",
            address="Ibn Gabirol 12",
            city_obj=tel_aviv,
        )

        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "Shufersal")
        choice_prompt = handle_deal_flow_response(self.user, locale, "Tel Aviv")
        self.assertIn("1)", choice_prompt)
        self.assertIn("2)", choice_prompt)
        next_prompt = handle_deal_flow_response(self.user, locale, "2")
        self.assertIn("what product", next_prompt.lower())

        answers = ["Milk 1L", "Liter", "1", "5.00", "1", "no", "no", "no"]
        summary = None
        for answer in answers:
            summary = handle_deal_flow_response(self.user, locale, answer)

        self.assertIn("Milk 1L", summary)
        report = PriceReport.objects.get()
        self.assertEqual(report.store_id, target.id)

    def test_unit_questions_not_skipped_when_product_has_defaults(self):
        locale = "en"
        Product.objects.create(
            name_he="Milk 3% 1L",
            name_en="Milk 3% 1L",
            default_unit_type="Liter",
            default_unit_quantity=Decimal("1.00"),
        )
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "Shufersal Givat Tal")
        handle_deal_flow_response(self.user, locale, "ראש העין")
        unit_prompt = handle_deal_flow_response(self.user, locale, "Milk 3% 1L")
        self.assertIn("unit is the package", unit_prompt.lower())
        qty_prompt = handle_deal_flow_response(self.user, locale, "Liter")
        self.assertIn("how many of that unit", qty_prompt.lower())
        price_prompt = handle_deal_flow_response(self.user, locale, "1")
        self.assertIn("what is the price", price_prompt.lower())
        handle_deal_flow_response(self.user, locale, "4.90")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "no")
        handle_deal_flow_response(self.user, locale, "no")
        summary = handle_deal_flow_response(self.user, locale, "no")
        self.assertIn("Milk 3% 1L", summary)
