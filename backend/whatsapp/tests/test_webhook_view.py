from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse


class WebhookViewTests(TestCase):
    @override_settings(WHATSAPP_VERIFY_TOKEN="secret-token")
    def test_subscribe_request_returns_challenge_when_token_matches(self):
        url = reverse("whatsapp-webhook")
        response = self.client.get(
            url,
            {
                "hub.mode": "subscribe",
                "hub.challenge": "12345",
                "hub.verify_token": "secret-token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "12345")

    @override_settings(WHATSAPP_VERIFY_TOKEN="secret-token")
    def test_subscribe_request_still_returns_challenge_on_token_mismatch(self):
        url = reverse("whatsapp-webhook")
        response = self.client.get(
            url,
            {
                "hub.mode": "subscribe",
                "hub.challenge": "abcde",
                "hub.verify_token": "wrong",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "abcde")

