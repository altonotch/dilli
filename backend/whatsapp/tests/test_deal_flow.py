from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from whatsapp.models import WAUser, DealReportSession
from whatsapp.deal_flow import start_add_deal_flow, handle_deal_flow_response
from pricing.models import PriceReport


class DealFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = WAUser.objects.create(wa_id_hash="hash", locale="en")

    def test_full_flow_collects_all_answers_and_returns_summary(self):
        locale = "en"
        prompt = start_add_deal_flow(self.user, locale)
        self.assertIn("which store", prompt.lower())

        flow = [
            ("Shufersal Givat Tal", "Which city"),
            ("Rosh HaAyin", "What product"),
            ("Milk 3% 1L", "What is the price"),
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
        self.assertIn("Milk 3% 1L", summary)
        self.assertIn("4.90", summary)
        self.assertIn("2 unit", summary)
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

    def test_invalid_price_prompts_again(self):
        locale = "en"
        start_add_deal_flow(self.user, locale)
        handle_deal_flow_response(self.user, locale, "Store A")
        handle_deal_flow_response(self.user, locale, "City A")
        handle_deal_flow_response(self.user, locale, "Product A")

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
