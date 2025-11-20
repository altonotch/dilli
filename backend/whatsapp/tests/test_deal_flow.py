from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from stores.models import Store, City
from whatsapp.models import WAUser, DealReportSession
from whatsapp.deal_flow import (
    start_add_deal_flow,
    handle_deal_flow_response,
    _find_store_candidates,
    FlowMessage,
)
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
        self.assertIn("which city", self._text(prompt).lower())

        flow = [
            ("ראש העין", "Which store"),
            ("Shufersal", "Which branch"),
            ("Givat Tal", "What product"),
            ("Milk 3% 1L", "Which brand"),
            ("Tnuva", "measured in units or weight"),
            ("Units", "which unit should i use"),
            ("Litres", "litres are in the package"),
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
        self.assertIn("Store: Shufersal", summary_text)
        self.assertIn("Branch or address: Givat Tal", summary_text)
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
        self.user.refresh_from_db()
        self.assertEqual(self.user.city, "Rosh HaAyin")
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
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, self.city.id)

    def test_invalid_price_prompts_again(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        store_prompt = handle_deal_flow_response(self.user, locale, "City A")
        self.assertIn("which store", self._text(store_prompt).lower())
        branch_prompt = handle_deal_flow_response(self.user, locale, "Store A")
        self.assertIn("branch", self._text(branch_prompt).lower())
        product_prompt = handle_deal_flow_response(self.user, locale, "Main Branch")
        self.assertIn("what product", self._text(product_prompt).lower())
        brand_prompt = handle_deal_flow_response(self.user, locale, "Product A")
        self.assertIn("which brand", self._text(brand_prompt).lower())
        measurement_prompt = handle_deal_flow_response(self.user, locale, "skip")
        self.assertIn("units or weight", self._text(measurement_prompt).lower())
        unit_prompt = handle_deal_flow_response(self.user, locale, "Units")
        self.assertIn("which unit", self._text(unit_prompt).lower())
        quantity_prompt = handle_deal_flow_response(self.user, locale, "Grams")
        self.assertIn("grams", self._text(quantity_prompt).lower())
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
        existing_store = Store.objects.create(
            name="Shufersal",
            display_name="Shufersal Givat Tal",
            city="Rosh HaAyin",
            city_obj=self.city,
        )
        existing_product = Product.objects.create(
            name_he="Milk 3% 1L",
            name_en="Milk 3% 1L",
            default_unit_type="Liter",
            default_unit_quantity=Decimal("1.00"),
        )

        start_add_deal_flow(self.user, locale)
        flow_answers = [
            "ראש העין",
            "Shufersal",
            "Givat Tal",
            "Milk 3% 1L",
            "skip",
            "Units",
            "Litres",
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

        summary_text = self._text(summary)
        self.assertIn("Store: Shufersal", summary_text)
        self.assertIn("Branch or address: Givat Tal", summary_text)
        report = PriceReport.objects.get()
        self.assertEqual(report.store_id, existing_store.id)
        self.assertEqual(report.product_id, existing_product.id)
        self.assertEqual(report.unit_measure_type, "Liter")
        self.assertEqual(report.unit_measure_quantity, Decimal("1.00"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, self.city.id)

    def test_city_lookup_populates_bilingual_names_from_city_model(self):
        locale = "en"
        tel_aviv = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "תל אביב")
        handle_deal_flow_response(self.user, locale, "Store Alpha")
        product_prompt = handle_deal_flow_response(self.user, locale, "תל אביב")
        self.assertIn("what product", self._text(product_prompt).lower())
        session = DealReportSession.objects.filter(user=self.user).latest("updated_at")
        self.assertEqual(session.data.get("city_he"), "תל אביב")
        self.assertEqual(session.data.get("city_en"), "Tel Aviv")
        self.assertEqual(session.data.get("city_id"), str(tel_aviv.id))
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, tel_aviv.id)

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
        handle_deal_flow_response(self.user, locale, "Tel Aviv")
        handle_deal_flow_response(self.user, locale, "Shufersal")
        # After providing branch, store disambiguation should occur automatically
        choice_prompt = handle_deal_flow_response(self.user, locale, "Center")
        choice_text = self._text(choice_prompt)
        self.assertIn("1)", choice_text)
        self.assertIn("2)", choice_text)
        next_prompt = handle_deal_flow_response(self.user, locale, "2")
        self.assertIn("what product", self._text(next_prompt).lower())

        answers = [
            "Milk 1L",
            "skip",
            "Units",
            "Litres",
            "1",
            "5.00",
            "1",
            "no",
            "no",
            "no",
        ]
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
        handle_deal_flow_response(self.user, locale, "ראש העין")
        handle_deal_flow_response(self.user, locale, "וויקטורי")
        handle_deal_flow_response(self.user, locale, "skip")
        handle_deal_flow_response(self.user, locale, "חלב")
        handle_deal_flow_response(self.user, locale, "דלג")
        handle_deal_flow_response(self.user, locale, "Units")
        handle_deal_flow_response(self.user, locale, "ליטר")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "5.00")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "לא")
        handle_deal_flow_response(self.user, locale, "לא")
        summary = handle_deal_flow_response(self.user, locale, "לא")
        self.assertIn("ויקטורי", self._text(summary))
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, self.city.id)
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
        handle_deal_flow_response(self.user, locale, "ראש העין")
        handle_deal_flow_response(self.user, locale, "Shufersal")
        handle_deal_flow_response(self.user, locale, "Givat Tal")
        brand_prompt = handle_deal_flow_response(self.user, locale, "Milk 3% 1L")
        self.assertIn("which brand", self._text(brand_prompt).lower())
        measurement_prompt = handle_deal_flow_response(self.user, locale, "skip")
        self.assertIn("units or weight", self._text(measurement_prompt).lower())
        unit_prompt = handle_deal_flow_response(self.user, locale, "Units")
        self.assertIn("which unit", self._text(unit_prompt).lower())
        qty_prompt = handle_deal_flow_response(self.user, locale, "Liter")
        self.assertIn("litres", self._text(qty_prompt).lower())
        price_prompt = handle_deal_flow_response(self.user, locale, "1")
        self.assertIn("what is the price", self._text(price_prompt).lower())
        handle_deal_flow_response(self.user, locale, "4.90")
        handle_deal_flow_response(self.user, locale, "1")
        handle_deal_flow_response(self.user, locale, "no")
        handle_deal_flow_response(self.user, locale, "no")
        summary = handle_deal_flow_response(self.user, locale, "no")
        self.assertIn("Milk 3% 1L", self._text(summary))

    def test_weight_category_skips_unit_type(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "ראש העין")
        handle_deal_flow_response(self.user, locale, "Shufersal")
        handle_deal_flow_response(self.user, locale, "Givat Tal")
        handle_deal_flow_response(self.user, locale, "Milk 3% 1L")
        measurement_prompt = handle_deal_flow_response(self.user, locale, "Brand A")
        self.assertIn("units or weight", self._text(measurement_prompt).lower())
        price_prompt = handle_deal_flow_response(self.user, locale, "Weight")
        self.assertIn("what is the price", self._text(price_prompt).lower())
        session = DealReportSession.objects.filter(user=self.user).latest("updated_at")
        self.assertEqual(session.data.get("unit_type_slug"), "kilogram")

    def test_city_prompt_offers_default_choice(self):
        locale = "en"
        saved_city = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        self.user.city_obj = saved_city
        self.user.city = saved_city.display_name
        self.user.save()
        # City should be the first prompt and include default/change buttons
        city_prompt = start_add_deal_flow(self.user, locale)
        self.assertTrue(hasattr(city_prompt, "buttons"))
        self.assertEqual(city_prompt.buttons[0]["id"], "city_default")
        self.assertEqual(city_prompt.buttons[1]["id"], "city_change")

    def test_city_change_button_requests_manual_input(self):
        locale = "en"
        saved_city = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        haifa = City.objects.create(name_he="חיפה", name_en="Haifa")
        self.user.city_obj = saved_city
        self.user.city = saved_city.display_name
        self.user.save()
        # City should be the first prompt
        city_prompt = start_add_deal_flow(self.user, locale)
        change_id = city_prompt.buttons[1]["id"]
        response = handle_deal_flow_response(self.user, locale, change_id)
        self.assertIn("type the city name", self._text(response).lower())
        next_prompt = handle_deal_flow_response(self.user, locale, "Haifa")
        # After city is chosen, we should be asked for store
        self.assertIn("which store", self._text(next_prompt).lower())
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, haifa.id)

    def test_default_city_button_advances_flow(self):
        locale = "en"
        saved_city = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        self.user.city_obj = saved_city
        self.user.city = saved_city.display_name
        self.user.save()
        # City should be the first prompt
        city_prompt = start_add_deal_flow(self.user, locale)
        default_id = city_prompt.buttons[0]["id"]
        store_prompt = handle_deal_flow_response(self.user, locale, default_id)
        self.assertIn("which store", self._text(store_prompt).lower())
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, saved_city.id)

    def test_city_disambiguation_prompts_buttons(self):
        locale = "en"
        tel_aviv = City.objects.create(name_he="תל אביב", name_en="Tel Aviv")
        City.objects.create(name_he="תל אביב יפו", name_en="Tel Aviv-Yafo")
        # Start flow and type partial city name to get city disambiguation
        start_add_deal_flow(self.user, locale)
        disambiguation = handle_deal_flow_response(self.user, locale, "Tel")
        self.assertIsInstance(disambiguation, FlowMessage)
        self.assertEqual(len(disambiguation.buttons), 2)
        pick_id = disambiguation.buttons[0]["id"]
        # After picking the city, we should be asked for the store
        store_prompt = handle_deal_flow_response(self.user, locale, pick_id)
        self.assertIn("which store", self._text(store_prompt).lower())
        self.user.refresh_from_db()
        self.assertEqual(self.user.city_obj_id, tel_aviv.id)
