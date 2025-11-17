from __future__ import annotations

from django.test import SimpleTestCase

from whatsapp.utils import detect_locale


class LanguageDetectionTests(SimpleTestCase):
    def test_detect_locale_prefers_langdetect_for_hebrew(self):
        text = "שלום זה מבחן זיהוי שפה ואני כותב בעברית מלאה"
        self.assertEqual(detect_locale(text), "he")

    def test_detect_locale_prefers_langdetect_for_english(self):
        text = "Hello there this is a language detection test written in English."
        self.assertEqual(detect_locale(text), "en")

    def test_detect_locale_falls_back_to_heuristic_for_symbols(self):
        text = "12345 :)"
        self.assertEqual(detect_locale(text), "en")
