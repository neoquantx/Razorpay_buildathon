import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

# Add src/ to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import guardrail

class TestGuardrailAndSafety(unittest.TestCase):
    def test_auto_approve(self):
        result = guardrail.check_action(300, False, [])
        self.assertEqual(result["decision"], "approved")

    def test_needs_confirmation(self):
        result = guardrail.check_action(1200, False, [])
        self.assertEqual(result["decision"], "needs_confirmation")

    def test_denied(self):
        result = guardrail.check_action(2500, False, [])
        self.assertEqual(result["decision"], "denied")

    def test_revoked(self):
        result = guardrail.check_action(300, True, [])
        self.assertEqual(result["decision"], "denied")

    def test_zero_amount_denied(self):
        result = guardrail.check_action(0, False, [])
        self.assertEqual(result["decision"], "denied")

    def test_negative_amount_denied(self):
        result = guardrail.check_action(-50, False, [])
        self.assertEqual(result["decision"], "denied")

    def test_structuring_within_window(self):
        now = datetime.now(timezone.utc)
        # Inside the 10 minute window
        recent_time = (now - timedelta(minutes=2)).isoformat()
        recent_amounts = [
            {"amount_inr": 700, "timestamp": recent_time},
            {"amount_inr": 700, "timestamp": recent_time}
        ]
        
        result = guardrail.check_action(700, False, recent_amounts)
        self.assertEqual(result["decision"], "denied")
        self.assertIn("Structuring detected", result["reason"])

    def test_large_single_amount_not_mislabeled_structuring(self):
        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(minutes=2)).isoformat()
        recent_amounts = [
            {"amount_inr": 300, "timestamp": recent_time}
        ]
        
        result = guardrail.check_action(2400, False, recent_amounts)
        self.assertEqual(result["decision"], "denied")
        self.assertIn("maximum allowed limit", result["reason"])
        self.assertNotIn("Structuring", result["reason"])

    def test_legitimate_multi_item_basket_not_flagged(self):
        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(minutes=2)).isoformat()
        recent_amounts = [
            {"amount_inr": 300, "timestamp": recent_time},
            {"amount_inr": 150, "timestamp": recent_time}
        ]
        
        result = guardrail.check_action(1200, False, recent_amounts)
        self.assertEqual(result["decision"], "needs_confirmation")

    def test_structuring_outside_window(self):
        now = datetime.now(timezone.utc)
        # Outside the 10 minute window
        recent_time = (now - timedelta(minutes=15)).isoformat()
        recent_amounts = [
            {"amount_inr": 300, "timestamp": recent_time},
            {"amount_inr": 300, "timestamp": recent_time}
        ]
        
        result = guardrail.check_action(300, False, recent_amounts)
        self.assertEqual(result["decision"], "approved")

if __name__ == '__main__':
    unittest.main()
