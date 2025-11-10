from __future__ import annotations

from django.test import TestCase

from stores.models import StoreChain, Store


class StoreModelTests(TestCase):
    def test_storechain_populates_missing_names(self):
        chain = StoreChain.objects.create(name="SuperChain", slug="super")
        self.assertEqual(chain.name_he, "SuperChain")
        self.assertEqual(chain.name_en, "SuperChain")

    def test_store_populates_missing_names(self):
        chain = StoreChain.objects.create(name="Chain", slug="chain")
        store = Store.objects.create(name="My Store", chain=chain)
        self.assertEqual(store.name_he, "My Store")
        self.assertEqual(store.name_en, "My Store")
