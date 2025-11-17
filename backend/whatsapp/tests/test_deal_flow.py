from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from stores.models import Store, City
from whatsapp.models import WAUser, DealReportSession
from whatsapp.deal_flow import start_add_deal_flow, handle_deal_flow_response, _find_store_candidates
from pricing.models import PriceReport


class DealFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = WAUser.objects.create(wa_id_hash="hash", locale="en")
        self.city = City.objects.create(name_he="ראש העין", name_en="Rosh HaAyin")

    def _text(self, reply):
        return reply.text if hasattr(reply, "text") else reply

    def test_full_flow_collects_all_answers_and_returns_summary(self):
        locale = "en"
        prompt = start_add_deal_flow(self.user, locale)
        self.assertIn("which store", self._text(prompt).lower())

        flow = [
            ("Shufersal Givat Tal", "Which city"),
            ("ראש העין", "What product"),
            ("Milk 3% 1L", "Which brand"),
            ("Tnuva", "What unit is the package"),
            ("Liter", "How many of that unit"),
            ("1", "What is the price"),
            ("4.90", "How many units"),
            ("2", "Is this deal only for club"),
            ("yes", "Is there a quantity limit"),
            ("3", "Is there a minimum cart"),
        ]

        for answer, expected_prompt in flow:
            response = handle_deal_flow_response(self.user, locale, answer)
            self.assertIn(expected_prompt.lower(), self._text(response).lower())

        summary = handle_deal_flow_response(self.user, locale, "100")
        summary_text = self._text(summary)
        self.assertIn("Shufersal Givat Tal", summary_text)
        self.assertIn("Rosh HaAyin", summary_text)
        self.assertIn("ראש העין", summary_text)
        self.assertIn("Milk 3% 1L", summary_text)
        self.assertIn("Brand: Tnuva", summary_text)
        self.assertIn("4.90", summary_text)
        self.assertIn("2 unit", summary_text)
        self.assertIn("Liter", summary_text)
        self.assertIn("awaiting moderation", summary_text.lower())
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
        self.assertEqual(pr.product.brand, "Tnuva")
        self.assertEqual(pr.unit_measure_type, "Liter")
        self.assertEqual(pr.unit_measure_quantity, Decimal("1.00"))

    def test_invalid_price_prompts_again(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "Store A")
        product_prompt = handle_deal_flow_response(self.user, locale, "City A")
        self.assertIn("what product", self._text(product_prompt).lower())
        brand_prompt = handle_deal_flow_response(self.user, locale, "Product A")
        self.assertIn("which brand", self._text(brand_prompt).lower())
        handle_deal_flow_response(self.user, locale, "skip")
        handle_deal_flow_response(self.user, locale, "Bottle")
        handle_deal_flow_response(self.user, locale, "1")

        error = handle_deal_flow_response(self.user, locale, "abc")
        self.assertIn("digits", self._text(error).lower())
        self.assertEqual(PriceReport.objects.count(), 0)

        next_prompt = handle_deal_flow_response(self.user, locale, "5.10")
        self.assertIn("how many units", self._text(next_prompt).lower())

    def test_cancel_flow_marks_session_inactive(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        cancel_msg = handle_deal_flow_response(self.user, locale, "cancel")
        self.assertIn("canceled", self._text(cancel_msg).lower())
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
            "skip",
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

        self.assertIn("Shufersal Givat Tal", self._text(summary))
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
        self.assertIn("what product", self._text(product_prompt).lower())
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
        choice_text = self._text(choice_prompt)
        self.assertIn("1)", choice_text)
        self.assertIn("2)", choice_text)
        next_prompt = handle_deal_flow_response(self.user, locale, "2")
        self.assertIn("what product", self._text(next_prompt).lower())

        answers = ["Milk 1L", "skip", "Liter", "1", "5.00", "1", "no", "no", "no"]
        summary = None
        for answer in answers:
            summary = handle_deal_flow_response(self.user, locale, answer)

        self.assertIn("Milk 1L", self._text(summary))
        report = PriceReport.objects.get()
        self.assertEqual(report.store_id, target.id)

    def test_store_aliases_are_matched(self):
        locale = "he"
        store = Store.objects.create(
            name="ויקטורי",
            city="ראש העין",
            city_obj=self.city,
            name_aliases_he=["וויקטורי"],
        )
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "וויקטורי")
        handle_deal_flow_response(self.user, locale, "ראש העין")
        handle_deal_flow_response(self.user, locale, "חלב")
        handle_deal_flow_response(self.user, locale, "דלג")
        handle_deal_flow_response(self.user, locale, "ליטר")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "5.00")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "לא")
        handle_deal_flow_response(self.user, locale, "לא")
        summary = handle_deal_flow_response(self.user, locale, "לא")
        self.assertIn("ויקטורי", self._text(summary))
        report = PriceReport.objects.get()
        self.assertEqual(report.store_id, store.id)

    def test_hebrew_variants_return_identical_store_candidates(self):
        Store.objects.create(
            name="ויקטורי",
            display_name="ויקטורי ראש העין",
            city="ראש העין",
            city_obj=self.city,
            name_aliases_he=["וויקטורי"],
        )
        Store.objects.create(
            name="ויקטורי הירוקה",
            display_name="ויקטורי הירוקה",
            city="ראש העין",
            city_obj=self.city,
            name_aliases_he=["וויקטורי הירוקה"],
        )
        data = {
            "city": "ראש העין",
            "city_he": "ראש העין",
            "city_id": str(self.city.id),
        }
        direct = _find_store_candidates("ויקטורי", data)
        alias = _find_store_candidates("וויקטורי", data)
        self.assertEqual([store.id for store in direct], [store.id for store in alias])
        self.assertGreater(len(direct), 0)

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
        brand_prompt = handle_deal_flow_response(self.user, locale, "Milk 3% 1L")
        self.assertIn("which brand", self._text(brand_prompt).lower())
        unit_prompt = handle_deal_flow_response(self.user, locale, "skip")
        self.assertIn("unit is the package", self._text(unit_prompt).lower())
        qty_prompt = handle_deal_flow_response(self.user, locale, "Liter")
        self.assertIn("how many of that unit", self._text(qty_prompt).lower())
        price_prompt = handle_deal_flow_response(self.user, locale, "1")
        self.assertIn("what is the price", self._text(price_prompt).lower())
        handle_deal_flow_response(self.user, locale, "4.90")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "no")
        handle_deal_flow_response(self.user, locale, "no")
        summary = handle_deal_flow_response(self.user, locale, "no")
        self.assertIn("Milk 3% 1L", self._text(summary))
