from __future__ import annotations

from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import TestCase, RequestFactory

from catalog.models import Product
from stores.models import Store
from whatsapp.models import WAUser
from pricing.models import PriceReport, StoreProductSnapshot
from pricing.admin import PriceReportAdmin


class PriceReportAdminTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="moderator", email="moderator@example.com", password="pwd"
        )
        self.store = Store.objects.create(name="Test Store", city="Test City")
        self.product = Product.objects.create(name_he="Milk", name_en="Milk")
        self.wa_user = WAUser.objects.create(wa_id_hash="hash", wa_number="9721111111", locale="en")
        self.admin_site = admin.sites.AdminSite()
        self.model_admin = PriceReportAdmin(PriceReport, self.admin_site)

    def _make_request(self, data: dict[str, str]):
        request = self.factory.post("/", data)
        request.user = self.admin_user
        request.session = {}
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def _create_report(self) -> PriceReport:
        return PriceReport.objects.create(
            user=self.wa_user,
            product=self.product,
            store=self.store,
            price="4.90",
            units_in_price=1,
            observed_at="2025-01-01T00:00:00Z",
        )

    @mock.patch("pricing.admin.send_whatsapp_text")
    def test_mark_reports_approved_sets_fields_and_updates_snapshot(self, mock_send):
        report = self._create_report()
        request = self._make_request({})

        self.model_admin.mark_reports_approved(
            request, PriceReport.objects.filter(pk=report.pk)
        )
        report.refresh_from_db()

        self.assertFalse(report.needs_moderation)
        self.assertEqual(report.moderated_by, self.admin_user)
        self.assertIsNotNone(report.moderated_at)
        self.assertEqual(report.moderation_reason, "")
        snapshot = StoreProductSnapshot.objects.get(product=self.product, store=self.store)
        self.assertEqual(snapshot.confirmation_count, 1)
        mock_send.assert_called_once()

    def test_mark_reports_rejected_requires_reason_and_sets_fields(self):
        report = self._create_report()
        request_missing = self._make_request({})
        self.model_admin.mark_reports_rejected(
            request_missing, PriceReport.objects.filter(pk=report.pk)
        )
        report.refresh_from_db()
        self.assertTrue(report.needs_moderation)
        self.assertIsNone(report.moderated_at)

        reason = "Incomplete receipt"
        request = self._make_request({"rejection_reason": reason})
        self.model_admin.mark_reports_rejected(
            request, PriceReport.objects.filter(pk=report.pk)
        )
        report.refresh_from_db()

        self.assertFalse(report.needs_moderation)
        self.assertEqual(report.moderated_by, self.admin_user)
        self.assertIn("Incomplete", report.moderation_reason)
        self.assertEqual(StoreProductSnapshot.objects.count(), 0)

    @mock.patch("pricing.admin.send_whatsapp_text")
    def test_approval_increments_existing_snapshot(self, mock_send):
        snapshot = StoreProductSnapshot.objects.create(
            product=self.product,
            store=self.store,
            last_price="3.10",
            last_observed_at="2025-01-01T00:00:00Z",
            confirmation_count=2,
        )
        report = self._create_report()
        request = self._make_request({})
        self.model_admin.mark_reports_approved(
            request, PriceReport.objects.filter(pk=report.pk)
        )
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.confirmation_count, 3)
        mock_send.assert_called_once()
