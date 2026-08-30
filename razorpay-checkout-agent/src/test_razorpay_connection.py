import os
import sys
import razorpay
from dotenv import load_dotenv

def main():
    # Load environment variables from .env file
    load_dotenv()
    
    # Check if the API keys are set
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    
    if not key_id or key_id == "your_key_id_here" or not key_secret or key_secret == "your_key_secret_here":
        print("Error: Razorpay credentials are not set correctly in the .env file.")
        print("Please update your .env file with your test RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
        sys.exit(1)
        
    try:
        print("Initializing Razorpay client...")
        client = razorpay.Client(auth=(key_id, key_secret))
        
        print("Creating a test order...")
        # Amount is in paise (100 paise = 1 INR)
        order_data = {
            "amount": 100,
            "currency": "INR",
            "receipt": "test_receipt_001",
            "notes": {
                "description": "Test order for connection verification"
            }
        }
        
        order = client.order.create(data=order_data)
        
        print("\n--- Razorpay Order Response ---")
        print(f"Order ID: {order['id']}")
        print(f"Amount: {order['amount'] / 100} INR")
        print(f"Status: {order['status']}")
        print("-------------------------------")
        print("\nSuccess! Razorpay API connection is working.")
        print("NOTE: This was a TEST MODE order. No real money was involved.")
        
    except Exception as e:
        print("\nError connecting to Razorpay API:")
        print(f"Details: {str(e)}")
        print("Please check your Razorpay test keys and internet connection.")

if __name__ == "__main__":
    main()
