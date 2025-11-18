from __future__ import annotations

from django.test import TestCase, override_settings

from whatsapp.handlers import _build_user_context
from whatsapp.models import WAUser
from whatsapp.utils import compute_wa_hash


@override_settings(WA_SALT="test-salt")
class LanguageFlowHandlerTests(TestCase):
    def _build_text_msg(self, text: str) -> dict:
        return {"type": "text", "text": {"body": text}}

    def test_new_user_non_numeric_hebrew_detects_he(self):
        wa_norm = "9725550001"
        msg = self._build_text_msg("שלום זה מבחן זיהוי שפה בעברית מלאה עם כמה מילים")

        ctx = _build_user_context(
            wa_norm=wa_norm,
            msg=msg,
            contacts={},
            value={},
        )

        self.assertTrue(ctx.created)
        self.assertEqual(ctx.current_locale, "he")
        # User is persisted with detected locale
        self.assertEqual(ctx.user.locale, "he")

    def test_new_user_non_numeric_english_detects_en(self):
        wa_norm = "9725550002"
        msg = self._build_text_msg(
            "Hello there this is a language detection test written fully in English."
        )

        ctx = _build_user_context(
            wa_norm=wa_norm,
            msg=msg,
            contacts={},
            value={},
        )

        self.assertTrue(ctx.created)
        self.assertEqual(ctx.current_locale, "en")
        self.assertEqual(ctx.user.locale, "en")

    def test_new_user_first_message_is_digit_defaults_to_en_and_does_not_apply_lang_choice(self):
        wa_norm = "9725550003"
        msg = self._build_text_msg("1")

        ctx = _build_user_context(
            wa_norm=wa_norm,
            msg=msg,
            contacts={},
            value={},
        )

        # We capture the intent but do NOT change locale based on a bare digit
        self.assertTrue(ctx.created)
        self.assertEqual(ctx.lang_choice, "he")  # parsed from "1"
        self.assertEqual(ctx.current_locale, "en")  # defaults to en for numeric-only
        self.assertEqual(ctx.user.locale, "en")

    def test_existing_user_hebrew_sends_1_locale_does_not_flip(self):
        wa_norm = "9725550004"
        wa_hash = compute_wa_hash(wa_norm)
        # Pre-create user with Hebrew locale
        WAUser.objects.create(wa_id_hash=wa_hash, locale="he", wa_number=wa_norm)

        msg = self._build_text_msg("1")

        ctx = _build_user_context(
            wa_norm=wa_norm,
            msg=msg,
            contacts={},
            value={},
        )

        self.assertFalse(ctx.created)
        # Even though lang_choice is "he" for digit 1, existing locale should prevail
        self.assertEqual(ctx.lang_choice, "he")
        self.assertEqual(ctx.current_locale, "he")
        # Locale on the user remains unchanged
        ctx.user.refresh_from_db()
        self.assertEqual(ctx.user.locale, "he")

    def test_existing_user_english_sends_2_locale_does_not_flip(self):
        wa_norm = "9725550005"
        wa_hash = compute_wa_hash(wa_norm)
        # Pre-create user with English locale
        WAUser.objects.create(wa_id_hash=wa_hash, locale="en", wa_number=wa_norm)

        msg = self._build_text_msg("2")

        ctx = _build_user_context(
            wa_norm=wa_norm,
            msg=msg,
            contacts={},
            value={},
        )

        self.assertFalse(ctx.created)
        # lang_choice is "en" for digit 2, but locale must remain the stored one
        self.assertEqual(ctx.lang_choice, "en")
        self.assertEqual(ctx.current_locale, "en")
        ctx.user.refresh_from_db()
        self.assertEqual(ctx.user.locale, "en")
