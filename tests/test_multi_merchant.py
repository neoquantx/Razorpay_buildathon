import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Mock heavy external dependencies (same pattern as test_idempotency.py)
sys.modules.setdefault('razorpay', MagicMock())
sys.modules.setdefault('dotenv', MagicMock())

import multi_merchant
import payment
import session_state


class TestFindCheapest(unittest.TestCase):
    """Test multi_merchant.find_cheapest against the three merchant catalogs."""

    # ── jacket: Value Mart is cheapest at ₹1150 ──────────────────────
    def test_jacket_cheapest_is_value_mart(self):
        result = multi_merchant.find_cheapest("jacket")
        self.assertEqual(result["cheapest_merchant_id"], "value_mart")
        self.assertEqual(result["cheapest_price_inr"], 1150)
        # All three merchants carry it
        for entry in result["comparison"]:
            self.assertTrue(entry["found"], f"{entry['merchant_id']} should stock jacket")

    # ── t-shirt: Trail Supply is cheapest at ₹280 ────────────────────
    def test_tshirt_cheapest_is_trail_supply(self):
        result = multi_merchant.find_cheapest("t-shirt")
        self.assertEqual(result["cheapest_merchant_id"], "trail_supply")
        self.assertEqual(result["cheapest_price_inr"], 280)

    # ── Comparison list is sorted cheapest-first ──────────────────────
    def test_comparison_sorted_by_price(self):
        result = multi_merchant.find_cheapest("cap")
        prices = [e["price_inr"] for e in result["comparison"] if e["found"]]
        self.assertEqual(prices, sorted(prices))

    # ── Case-insensitive lookup ───────────────────────────────────────
    def test_case_insensitive(self):
        result = multi_merchant.find_cheapest("JACKET")
        self.assertEqual(result["cheapest_merchant_id"], "value_mart")

    # ── Item that no merchant stocks → clear not-found, no crash ──────
    def test_item_not_found_anywhere(self):
        result = multi_merchant.find_cheapest("quantum-umbrella")
        self.assertIsNone(result["cheapest_merchant_id"])
        self.assertIsNone(result["cheapest_price_inr"])
        self.assertEqual(result["status"], "not_found_anywhere")
        self.assertIn("quantum-umbrella", result["message"])


class TestGetMerchantCatalog(unittest.TestCase):
    def test_valid_merchant(self):
        catalog = multi_merchant.get_merchant_catalog("urban_threads")
        self.assertIn("t-shirt", catalog)

    def test_unknown_merchant_raises(self):
        with self.assertRaises(ValueError):
            multi_merchant.get_merchant_catalog("nonexistent_shop")


class TestBuyFromMerchant(unittest.TestCase):
    """Test buy_from_merchant with a mocked Razorpay client (same as test_idempotency.py)."""

    def setUp(self):
        os.environ["RAZORPAY_KEY_ID"] = "test_key_id"
        os.environ["RAZORPAY_KEY_SECRET"] = "test_key_secret"

    @patch('payment.razorpay.Client')
    def test_buy_approved_item(self, mock_razorpay_client):
        mock_instance = MagicMock()
        mock_razorpay_client.return_value = mock_instance
        mock_instance.order.create.return_value = {
            "id": "order_multi_001",
            "amount": 28000,  # 280 INR in paise
            "status": "created",
        }

        state = {"revoked": False, "recent_amounts": []}
        result = multi_merchant.buy_from_merchant(
            "trail_supply", "t-shirt", 1, state
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["amount_inr"], 280)
        self.assertEqual(result["merchant_id"], "trail_supply")
        self.assertEqual(result["item"], "t-shirt")

    @patch('payment.razorpay.Client')
    def test_buy_denied_over_max(self, mock_razorpay_client):
        """Buying enough to exceed max_allowed_limit_inr → denied."""
        state = {"revoked": False, "recent_amounts": []}
        # 2 × jacket at ₹1350 = ₹2700, above the ₹2000 max
        result = multi_merchant.buy_from_merchant(
            "trail_supply", "jacket", 2, state
        )
        self.assertEqual(result["status"], "denied")

    def test_buy_unknown_merchant(self):
        state = {"revoked": False, "recent_amounts": []}
        result = multi_merchant.buy_from_merchant(
            "fake_merchant", "jacket", 1, state
        )
        self.assertEqual(result["status"], "error")

    def test_buy_unknown_item(self):
        state = {"revoked": False, "recent_amounts": []}
        result = multi_merchant.buy_from_merchant(
            "value_mart", "quantum-umbrella", 1, state
        )
        self.assertEqual(result["status"], "error")

    @patch('payment.razorpay.Client')
    def test_buy_needs_confirmation(self, mock_razorpay_client):
        """Item between auto-approve and max → needs_confirmation."""
        state = {"revoked": False, "recent_amounts": []}
        # jacket at ₹1150 (value_mart) is above ₹500 auto-approve
        result = multi_merchant.buy_from_merchant(
            "value_mart", "jacket", 1, state
        )
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["total_inr"], 1150)

    @patch('payment.razorpay.Client')
    def test_buy_revoked(self, mock_razorpay_client):
        """Revoked session → denied."""
        state = {"revoked": True, "recent_amounts": []}
        result = multi_merchant.buy_from_merchant(
            "trail_supply", "cap", 1, state
        )
        self.assertEqual(result["status"], "denied")


if __name__ == "__main__":
    unittest.main()
