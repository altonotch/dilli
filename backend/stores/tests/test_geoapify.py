from __future__ import annotations

import json
from unittest import mock

from django.test import SimpleTestCase, override_settings

from stores.geoapify import search_place, geocode_store_name, GeoapifyError


class GeoapifyTests(SimpleTestCase):
    @override_settings(GEOAPIFY_API_KEY="test-key")
    @mock.patch("stores.geoapify.request.urlopen")
    def test_search_place_parses_results(self, mock_urlopen):
        payload = {
            "features": [
                {
                    "properties": {
                        "lat": 32.095,
                        "lon": 34.784,
                        "formatted": "Test Store, Tel Aviv",
                        "city": "Tel Aviv",
                    }
                }
            ]
        }
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        results = search_place("Test Store Tel Aviv")
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertAlmostEqual(result.latitude, 32.095)
        self.assertAlmostEqual(result.longitude, 34.784)
        self.assertEqual(result.city, "Tel Aviv")

    def test_geocode_store_requires_api_key(self):
        with self.assertRaises(GeoapifyError):
            geocode_store_name("Test", "City", api_key="")
