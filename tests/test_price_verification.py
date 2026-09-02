import sys
import os
import unittest

# price_check.py has zero SDK dependencies — import it directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from price_check import verify_item_price


class TestVerifyItemPrice(unittest.TestCase):
    """
    Unit tests for verify_item_price — pure logic, no Gemini, no mocking.

    products.json catalog (from config/products.json):
        t-shirt              ₹300
        jacket               ₹1200
        cap                  ₹150
        waterproofing spray  ₹250
    """

    # ------------------------------------------------------------------
    # 1. Exact catalog price for a known item → ok True
    # ------------------------------------------------------------------
    def test_exact_catalog_price_ok(self):
        result = verify_item_price("t-shirt", 300.0, {})
        self.assertTrue(result["ok"])

    def test_exact_catalog_price_jacket(self):
        result = verify_item_price("jacket", 1200.0, {})
        self.assertTrue(result["ok"])

    # ------------------------------------------------------------------
    # 2. Wrong price, no negotiation on record → ok False, "Price mismatch"
    # ------------------------------------------------------------------
    def test_wrong_price_no_negotiation(self):
        result = verify_item_price("t-shirt", 100.0, {})
        self.assertFalse(result["ok"])
        self.assertIn("Price mismatch", result["reason"])

    def test_wrong_price_no_negotiation_mentions_catalog_price(self):
        result = verify_item_price("jacket", 999.0, {})
        self.assertFalse(result["ok"])
        self.assertIn("1200", result["reason"])

    # ------------------------------------------------------------------
    # 3. Wrong price, but matching last_negotiation → ok True
    # ------------------------------------------------------------------
    def test_negotiated_price_accepted(self):
        state = {
            "last_negotiation": {
                "item_name": "t-shirt",
                "final_price_inr": 280.0,
            }
        }
        result = verify_item_price("t-shirt", 280.0, state)
        self.assertTrue(result["ok"])

    def test_negotiated_price_case_insensitive(self):
        """item_name casing in session state should not matter."""
        state = {
            "last_negotiation": {
                "item_name": "T-Shirt",
                "final_price_inr": 275.0,
            }
        }
        result = verify_item_price("t-shirt", 275.0, state)
        self.assertTrue(result["ok"])

    # ------------------------------------------------------------------
    # 4. Wrong price, last_negotiation for a DIFFERENT item → ok False
    # ------------------------------------------------------------------
    def test_negotiation_for_different_item_rejected(self):
        state = {
            "last_negotiation": {
                "item_name": "jacket",   # negotiation was for jacket, not t-shirt
                "final_price_inr": 280.0,
            }
        }
        result = verify_item_price("t-shirt", 280.0, state)
        self.assertFalse(result["ok"])
        self.assertIn("Price mismatch", result["reason"])

    def test_negotiation_price_mismatch_for_same_item(self):
        """Negotiation record for same item but DIFFERENT final price → denied."""
        state = {
            "last_negotiation": {
                "item_name": "t-shirt",
                "final_price_inr": 270.0,  # negotiated to 270, customer tries 200
            }
        }
        result = verify_item_price("t-shirt", 200.0, state)
        self.assertFalse(result["ok"])
        self.assertIn("Price mismatch", result["reason"])

    # ------------------------------------------------------------------
    # 5. Item not in products.json at all → ok True (documented limitation)
    # ------------------------------------------------------------------
    def test_unknown_item_passes(self):
        """Items outside the fixed catalog are not covered; we let them through."""
        result = verify_item_price("mystery-gadget-xyz", 9999.0, {})
        self.assertTrue(result["ok"])

    def test_unknown_item_custom_service(self):
        result = verify_item_price("custom-embroidery-service", 500.0, {})
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
