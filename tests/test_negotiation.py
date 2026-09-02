import sys
import os
import unittest

# Ensure src/ is on the path so negotiation can be imported directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import negotiation


class TestEvaluateNegotiation(unittest.TestCase):
    """Tests for negotiation.evaluate_negotiation().

    Policy loaded from config/policy.json:
        negotiation_floor_pct = 10   →  floor = catalog * 0.90
        min_amount_inr        = 1
    """

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _call(self, catalog, requested):
        return negotiation.evaluate_negotiation(catalog, requested)

    # ------------------------------------------------------------------
    # 1. Request within the floor → accepted
    # ------------------------------------------------------------------
    def test_accepted_within_floor(self):
        """₹950 off a ₹1000 item is a 5% discount — within the 10% floor."""
        result = self._call(1000.0, 950.0)
        self.assertEqual(result["decision"], "accepted")
        self.assertAlmostEqual(result["final_price_inr"], 950.0)
        self.assertIn("10%", result["reason"])

    def test_accepted_exactly_at_floor(self):
        """₹900 off a ₹1000 item is exactly at the 10% floor — still accepted."""
        result = self._call(1000.0, 900.0)
        self.assertEqual(result["decision"], "accepted")
        self.assertAlmostEqual(result["final_price_inr"], 900.0)

    # ------------------------------------------------------------------
    # 2. Request below the floor → countered at the computed floor price
    # ------------------------------------------------------------------
    def test_countered_below_floor(self):
        """₹800 off a ₹1000 item is 20% — exceeds the 10% floor; should counter."""
        result = self._call(1000.0, 800.0)
        self.assertEqual(result["decision"], "countered")
        # floor = 1000 * 0.90 = 900.00
        self.assertAlmostEqual(result["final_price_inr"], 900.0, places=2)

    def test_countered_floor_rounding(self):
        """Test that the counter price is rounded to 2 decimal places."""
        # floor = 333 * 0.90 = 299.70
        result = self._call(333.0, 200.0)
        self.assertEqual(result["decision"], "countered")
        self.assertEqual(result["final_price_inr"], round(333.0 * 0.90, 2))

    # ------------------------------------------------------------------
    # 3. Request at or above catalog price → no_discount_needed
    # ------------------------------------------------------------------
    def test_no_discount_needed_at_catalog(self):
        """Requesting the exact catalog price needs no discount."""
        result = self._call(1000.0, 1000.0)
        self.assertEqual(result["decision"], "no_discount_needed")
        self.assertAlmostEqual(result["final_price_inr"], 1000.0)

    def test_no_discount_needed_above_catalog(self):
        """Requesting more than the catalog price also needs no discount."""
        result = self._call(1000.0, 1200.0)
        self.assertEqual(result["decision"], "no_discount_needed")
        self.assertAlmostEqual(result["final_price_inr"], 1000.0)

    # ------------------------------------------------------------------
    # 4. Zero or negative requested price → rejected
    # ------------------------------------------------------------------
    def test_rejected_zero_price(self):
        """A zero requested price is invalid."""
        result = self._call(1000.0, 0.0)
        self.assertEqual(result["decision"], "rejected")
        self.assertNotIn("final_price_inr", result)

    def test_rejected_negative_price(self):
        """A negative requested price is invalid."""
        result = self._call(1000.0, -50.0)
        self.assertEqual(result["decision"], "rejected")
        self.assertNotIn("final_price_inr", result)

    def test_rejected_below_min_amount(self):
        """A price below MIN_AMOUNT_INR (1) must be rejected."""
        result = self._call(1000.0, 0.5)
        self.assertEqual(result["decision"], "rejected")


if __name__ == "__main__":
    unittest.main()
