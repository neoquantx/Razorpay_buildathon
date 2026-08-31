import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

# Mock modules before importing payment so the test can run without dependencies
sys.modules['razorpay'] = MagicMock()
sys.modules['dotenv'] = MagicMock()

import payment
import idempotency

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # We need mock env vars so payment.create_order doesn't fail on missing keys
        os.environ["RAZORPAY_KEY_ID"] = "test_key_id"
        os.environ["RAZORPAY_KEY_SECRET"] = "test_key_secret"

    @patch('payment.razorpay.Client')
    def test_same_idempotency_key(self, mock_razorpay_client):
        # Setup mock behavior
        mock_instance = MagicMock()
        mock_razorpay_client.return_value = mock_instance
        
        # We simulate what Razorpay returns
        mock_instance.order.create.return_value = {
            "id": "order_test123",
            "amount": 50000,  # paise
            "status": "created"
        }

        key = "test_key_same_" + os.urandom(4).hex()
        
        # First call
        res1 = payment.create_order(500, "Test item", idempotency_key=key)
        # Second call
        res2 = payment.create_order(500, "Test item", idempotency_key=key)

        # Assertions
        self.assertEqual(res1, res2)
        # Verify the underlying Razorpay client was only called once
        mock_instance.order.create.assert_called_once()

    @patch('payment.razorpay.Client')
    def test_different_idempotency_keys(self, mock_razorpay_client):
        # Setup mock behavior
        mock_instance = MagicMock()
        mock_razorpay_client.return_value = mock_instance
        
        mock_instance.order.create.side_effect = [
            {
                "id": "order_test_A",
                "amount": 50000,
                "status": "created"
            },
            {
                "id": "order_test_B",
                "amount": 50000,
                "status": "created"
            }
        ]

        key1 = "test_key_diff_1_" + os.urandom(4).hex()
        key2 = "test_key_diff_2_" + os.urandom(4).hex()
        
        # First call
        res1 = payment.create_order(500, "Test item A", idempotency_key=key1)
        # Second call
        res2 = payment.create_order(500, "Test item B", idempotency_key=key2)

        # Assertions
        self.assertNotEqual(res1["order_id"], res2["order_id"])
        # Verify the underlying Razorpay client was called twice
        self.assertEqual(mock_instance.order.create.call_count, 2)

if __name__ == '__main__':
    unittest.main()
