from __future__ import annotations
from unittest import mock

from django.test import SimpleTestCase, override_settings

from whatsapp.utils import (
    get_intro_message,
    get_intro_buttons,
    send_whatsapp_buttons,
    send_whatsapp_text,
)


class IntroFlowTests(SimpleTestCase):
    def test_intro_message_mentions_add_and_find(self):
        msg = get_intro_message("en")
        self.assertIn("add a deal", msg.lower())
        self.assertIn("find a deal", msg.lower())

    def test_intro_buttons_localized_to_hebrew(self):
        buttons = get_intro_buttons("he")
        titles = {btn["title"] for btn in buttons}
        self.assertIn("הוסף דיל", titles)
        self.assertIn("מצא דיל", titles)

    @override_settings(WHATSAPP_ACCESS_TOKEN="token", WHATSAPP_PHONE_NUMBER_ID="12345")
    @mock.patch("whatsapp.utils._execute_request")
    @mock.patch("whatsapp.utils._build_request")
    def test_send_buttons_uses_interactive_payload(self, mock_build, mock_exec):
        mock_build.side_effect = lambda payload: payload
        mock_exec.return_value = True
        body = "Choose an option"
        send_whatsapp_buttons(
            "972000000000",
            body,
            [{"id": "add_deal", "title": "Add a deal"}, {"id": "find_deal", "title": "Find a deal"}],
        )
        mock_build.assert_called_once()
        payload = mock_build.call_args[0][0]
        self.assertEqual(payload["type"], "interactive")
        self.assertEqual(payload["interactive"]["body"]["text"], body)
        self.assertEqual(len(payload["interactive"]["action"]["buttons"]), 2)
        mock_exec.assert_called_once_with(payload)

    @mock.patch("whatsapp.utils.send_whatsapp_text")
    def test_send_buttons_falls_back_to_text_when_empty(self, mock_text):
        send_whatsapp_buttons("9721", "Fallback body", buttons=[])
        mock_text.assert_called_once_with("9721", "Fallback body")
