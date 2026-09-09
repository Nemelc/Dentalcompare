import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import gacd_playwright_fast_v2 as gacd
from gacd_playwright_fast_v2 import PRODUCT_MARKER, html_candidate, valid_ref


class GacdPlaywrightV2Test(unittest.TestCase):
    def test_product_marker_accepts_gacd_variants(self):
        for text in ('Réf. GACD : 12345', 'Réf GACD 12345', 'Référence GACD: ABC-1'):
            with self.subTest(text=text):
                self.assertIsNotNone(PRODUCT_MARKER.search(text))

    def test_html_candidate(self):
        self.assertTrue(html_candidate('https://www.gacd.fr/produit-test.html'))
        self.assertFalse(html_candidate('https://www.gacd.fr/customer/account.html'))
        self.assertFalse(html_candidate('https://www.gacd.fr/catalogue/'))

    def test_valid_ref(self):
        self.assertEqual(valid_ref('ABC-123'), 'ABC-123')
        self.assertEqual(valid_ref('Référence'), '')

    def test_listing_is_promoted_to_pending_product(self):
        with TemporaryDirectory() as tmp:
            old_data, old_db = gacd.DATA, gacd.DB
            try:
                gacd.DATA = Path(tmp)
                gacd.DB = Path(tmp) / 'queue.sqlite3'
                store = gacd.Store()
                url = 'https://www.gacd.fr/produit-test.html'
                store.add({url}, 'listing')
                store.done(url)
                store.add({url}, 'product')
                self.assertEqual(store.next('product'), url)
                store.db.close()
            finally:
                gacd.DATA, gacd.DB = old_data, old_db


if __name__ == '__main__':
    unittest.main()
