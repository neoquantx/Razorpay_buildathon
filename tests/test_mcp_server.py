import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add src/ to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

sys.modules['mcp'] = MagicMock()
mock_server_module = MagicMock()
sys.modules['mcp.server'] = mock_server_module

# Make the decorator return the original function
def mock_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator

class MockMCPServer:
    def __init__(self, *args, **kwargs):
        self.tool = mock_decorator
        self.resource = mock_decorator
        self.run = MagicMock()

mock_server_module.MCPServer = MockMCPServer

import mcp_server
import session_state
import idempotency

class TestMCPServer(unittest.TestCase):
    def setUp(self):
        # Reset any state
        idempotency._store = {}
        session_state.save_state({"revoked": False, "recent_amounts": []})

    @patch('payment.razorpay.Client')
    def test_create_purchase_order_id_regression(self, mock_razorpay_client):
        # Setup mock exactly like test_idempotency.py
        mock_client_instance = MagicMock()
        mock_razorpay_client.return_value = mock_client_instance
        
        # Configure the mock to return a dictionary matching Razorpay's API response
        mock_client_instance.order.create.return_value = {
            "id": "order_mock123",
            "amount": 30000,
            "status": "created"
        }
        
        # Call the MCP server's create_purchase tool directly
        result = mcp_server.create_purchase(item_name="t-shirt", quantity=1)
        
        # Verify the success and check that order_id is properly populated
        self.assertEqual(result.get("status"), "success")
        self.assertIsNotNone(result.get("order_id"))
        self.assertEqual(result.get("order_id"), "order_mock123")
        self.assertEqual(result.get("amount_inr"), 300)

if __name__ == '__main__':
    unittest.main()
