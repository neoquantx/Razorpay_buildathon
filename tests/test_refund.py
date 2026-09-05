"""Tests for refund_payment reason validation and audit logging."""
import sys
import os
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Add src/ to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import audit_log
import idempotency
import payment


class TestRefundReasonValidation(unittest.TestCase):
    """Test the refund_payment handler logic extracted from agent.py."""

    # ------------------------------------------------------------------
    # Helper: replicate the refund handler's core logic so we can unit-test
    # it without starting Gemini / the full REPL loop.
    # ------------------------------------------------------------------
    @staticmethod
    def _handle_refund(customer_reason: str, recent_amounts: list) -> dict:
        """
        Mirrors the refund_payment branch in agent.py's main loop.
        Returns (refund_result_dict).
        """
        refund_result = {}

        # Validate reason
        if not customer_reason or not customer_reason.strip() or customer_reason.strip() == "refund_payment":
            deny_reason = "A reason is required before a refund can be processed."
            audit_log.log_action("refund_payment", 0, deny_reason, "denied_missing_reason", customer_reason=customer_reason)
            return {"status": "denied", "reason": deny_reason}

        if not recent_amounts:
            return {"status": "failed", "reason": "No recent purchases found to refund."}

        last_purchase = recent_amounts[-1]
        last_order_id = last_purchase.get("order_id")
        amount_inr = last_purchase.get("amount_inr", 0.0)
        purchase_time = datetime.fromisoformat(last_purchase["timestamp"])

        if purchase_time.tzinfo is None:
            purchase_time = purchase_time.replace(tzinfo=timezone.utc)

        time_diff = datetime.now(timezone.utc) - purchase_time

        if time_diff.total_seconds() > 600:
            reason = "Refund window expired. Refunds are only allowed within 10 minutes of purchase."
            audit_log.log_action("refund_payment", amount_inr, reason, "denied_time_boundary", customer_reason=customer_reason)
            return {"status": "denied", "reason": reason}
        elif not last_order_id:
            reason = "No valid transaction ID found for the last purchase."
            audit_log.log_action("refund_payment", amount_inr, reason, "failed", customer_reason=customer_reason)
            return {"status": "failed", "reason": reason}
        else:
            refund_key = f"refund_{last_order_id}"
            if idempotency.get_cached_result(refund_key):
                reason = f"Transaction {last_order_id} has already been refunded."
                audit_log.log_action("refund_payment", amount_inr, reason, "denied_idempotent", customer_reason=customer_reason)
                return {"status": "denied", "reason": reason}
            else:
                try:
                    refund_resp = payment.refund_payment(last_order_id, customer_reason)
                    reason = f"Successfully initiated refund for {last_order_id}."
                    audit_log.log_action("refund_payment", amount_inr, reason, "approved", customer_reason=customer_reason)
                    idempotency.save_result(refund_key, {"refund_id": refund_resp.get("refund_id", "mock_refund")})
                    return {"status": "success", "message": reason}
                except Exception as e:
                    audit_log.log_action("refund_payment", amount_inr, str(e), "failed", customer_reason=customer_reason)
                    return {"status": "failed", "error": str(e)}

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------
    def setUp(self):
        """Use a temporary audit log file for each test."""
        self._orig_log_file = audit_log.LOG_FILE
        self._tmp_log = os.path.join(
            os.path.dirname(__file__), "_test_audit_log.jsonl"
        )
        audit_log.LOG_FILE = self._tmp_log
        # Ensure clean state
        if os.path.exists(self._tmp_log):
            os.remove(self._tmp_log)

    def tearDown(self):
        audit_log.LOG_FILE = self._orig_log_file
        if os.path.exists(self._tmp_log):
            os.remove(self._tmp_log)

    # ------------------------------------------------------------------
    # Test 1: empty reason → denied
    # ------------------------------------------------------------------
    def test_empty_reason_denied(self):
        """An empty reason must be rejected immediately."""
        result = self._handle_refund("", recent_amounts=[])
        self.assertEqual(result["status"], "denied")
        self.assertEqual(
            result["reason"],
            "A reason is required before a refund can be processed."
        )

        # Verify the audit entry was written with the denial
        logs = audit_log.read_all_logs()
        self.assertTrue(len(logs) >= 1)
        entry = logs[-1]
        self.assertEqual(entry["outcome"], "denied_missing_reason")

    # ------------------------------------------------------------------
    # Test 2: valid reason within time window → approved,
    #          customer_reason present in audit log
    # ------------------------------------------------------------------
    @patch("payment.refund_payment")
    @patch("idempotency.get_cached_result", return_value=None)
    @patch("idempotency.save_result")
    def test_valid_reason_approved_with_customer_reason(
        self, mock_save, mock_cache, mock_refund
    ):
        """A real reason ('wrong size') within the refund window must be approved,
        and customer_reason must appear in the logged audit entry."""
        mock_refund.return_value = {"status": "success", "refund_id": "rfnd_test123"}

        now = datetime.now(timezone.utc)
        recent = [
            {
                "amount_inr": 499,
                "timestamp": (now - timedelta(minutes=2)).isoformat(),
                "order_id": "order_xyz",
            }
        ]

        result = self._handle_refund("wrong size", recent_amounts=recent)
        self.assertEqual(result["status"], "success")
        self.assertIn("order_xyz", result["message"])

        # Verify audit log entry
        logs = audit_log.read_all_logs()
        self.assertTrue(len(logs) >= 1)
        entry = logs[-1]
        self.assertEqual(entry["outcome"], "approved")
        self.assertEqual(entry["customer_reason"], "wrong size")
        # Ensure system reason and customer reason are separate fields
        self.assertIn("reason", entry)
        self.assertNotEqual(entry["reason"], entry["customer_reason"])


if __name__ == "__main__":
    unittest.main()
