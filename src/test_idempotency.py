import os
from idempotency import generate_key
import payment

def main():
    amount = 150.0
    description = "Test item for idempotency"
    
    key = generate_key(amount, description)
    print(f"Generated idempotency key: {key}")
    
    print("\n--- Call 1 ---")
    try:
        result1 = payment.create_order(amount, description, idempotency_key=key)
        print("Result 1:", result1)
    except Exception as e:
        print("Error on Call 1:", e)
        
    print("\n--- Call 2 ---")
    try:
        result2 = payment.create_order(amount, description, idempotency_key=key)
        print("Result 2:", result2)
        if result1 == result2:
            print("\nA real duplicate Razorpay order was avoided! The second call returned the exact same cached order.")
        else:
            print("\nWarning: The results differ.")
    except Exception as e:
        print("Error on Call 2:", e)

if __name__ == "__main__":
    main()
