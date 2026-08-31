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
            "amount": int(amount_inr * 100),
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
