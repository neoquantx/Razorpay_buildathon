AUTO_APPROVE_LIMIT = 500
MAX_ALLOWED_LIMIT = 2000

def check_action(amount_inr: float, revoked: bool) -> dict:
    if revoked:
        return {
            "decision": "denied",
            "reason": "The action has been revoked."
        }
        
    if amount_inr <= AUTO_APPROVE_LIMIT:
        return {
            "decision": "approved",
            "reason": f"Amount {amount_inr} INR is under the auto-approve limit of {AUTO_APPROVE_LIMIT} INR."
        }
    elif amount_inr <= MAX_ALLOWED_LIMIT:
        return {
            "decision": "needs_confirmation",
            "reason": f"Amount {amount_inr} INR is between {AUTO_APPROVE_LIMIT} and {MAX_ALLOWED_LIMIT} INR, requiring manual confirmation."
        }
    else:
        return {
            "decision": "denied",
            "reason": f"Amount {amount_inr} INR exceeds the maximum allowed limit of {MAX_ALLOWED_LIMIT} INR."
        }

if __name__ == "__main__":
    print("Testing amount: 300, revoked: False")
    print(check_action(300, False))
    
    print("\nTesting amount: 1000, revoked: False")
    print(check_action(1000, False))
    
    print("\nTesting amount: 2500, revoked: False")
    print(check_action(2500, False))
    
    print("\nTesting amount: 100, revoked: True")
    print(check_action(100, True))
