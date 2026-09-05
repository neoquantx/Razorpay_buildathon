"""Razorpay payment gateway integration and order creation."""
import os
import razorpay
from dotenv import load_dotenv
from pathlib import Path

class PaymentFailedError(Exception):
    pass

def create_order(amount_inr: float, description: str, idempotency_key: str = None) -> dict:
    if "faildemo" in description.lower():
        raise PaymentFailedError("Payment could not be completed: insufficient test balance simulation.")

    if idempotency_key:
        import idempotency
        cached = idempotency.get_cached_result(idempotency_key)
        if cached:
            return cached["order"]

    # Load environment variables from .env file
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    
    # Check if the API keys are set
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    
    if not key_id or key_id == "your_key_id_here" or not key_secret or key_secret == "your_key_secret_here":
        raise ValueError("Error: Razorpay credentials are not set correctly in the .env file.")
        
    try:
        client = razorpay.Client(auth=(key_id, key_secret))
        
        # Amount is in paise (100 paise = 1 INR)
        order_data = {
            "amount": int(round(amount_inr * 100)),
            "currency": "INR",
            "notes": {
                "description": description
            }
        }
        
        order = client.order.create(data=order_data)
        
        result = {
            "order_id": order["id"],
            "amount": order["amount"] / 100,
            "status": order["status"]
        }
        
        if idempotency_key:
            import idempotency
            idempotency.save_result(idempotency_key, {"order": result})
            
        return result
    except Exception as e:
        raise Exception(f"Failed to create Razorpay order: {str(e)}")

def refund_payment(transaction_id: str, reason: str) -> dict:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    
    if not key_id or not key_secret:
        raise ValueError("Error: Razorpay credentials are not set correctly in the .env file.")
        
    try:
        client = razorpay.Client(auth=(key_id, key_secret))
        # Note: In a real flow, you would pass the payment_id here.
        # If transaction_id is an order_id without a captured payment, this will raise a Razorpay Error.
        # This can be handled gracefully by the agent.
        
        # Try to find payments for this order first
        payments = client.order.payments(transaction_id)
        if payments.get("items"):
            payment_id = payments["items"][0]["id"]
            refund = client.payment.refund(payment_id, {})
            return {"status": "success", "refund_id": refund["id"]}
        else:
            # No payments found, simulate refund or throw error
            # For demonstration, we'll try to initiate a refund directly to see SDK behavior
            # or raise a specific error that the agent can handle gracefully.
            raise PaymentFailedError(f"Cannot refund: No completed payment found for order {transaction_id}")
            
    except Exception as e:
        raise Exception(f"Failed to initiate Razorpay refund: {str(e)}")
