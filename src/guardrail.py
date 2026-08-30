import json
import os
from datetime import datetime, timezone, timedelta

# Load policy.json at startup
POLICY_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'policy.json')

try:
    with open(POLICY_PATH, 'r') as f:
        policy = json.load(f)
        AUTO_APPROVE_LIMIT = policy['auto_approve_limit_inr']
        MAX_ALLOWED_LIMIT = policy['max_allowed_limit_inr']
        STRUCTURING_WINDOW_MINUTES = policy['structuring_window_minutes']
        STRUCTURING_LIMIT_INR = policy['structuring_limit_inr']
        MIN_AMOUNT_INR = policy.get('min_amount_inr', 1)
except FileNotFoundError:
    raise RuntimeError(f"Policy file not found at {POLICY_PATH}")
except (json.JSONDecodeError, KeyError) as e:
    raise RuntimeError(f"Policy file is malformed: {e}")

def check_action(amount_inr: float, revoked: bool, recent_amounts: list[dict]) -> dict:
    if amount_inr < MIN_AMOUNT_INR:
        return {
            "decision": "denied",
            "reason": "Amount is below the minimum valid payment amount — likely a manipulated or invalid request."
        }
    
    if revoked:
        return {
            "decision": "denied",
            "reason": "The action has been revoked."
        }
    
    # Structuring check
    now = datetime.now(timezone.utc)
    structuring_window_start = now - timedelta(minutes=STRUCTURING_WINDOW_MINUTES)
    
    recent_total = 0.0
    for entry in recent_amounts:
        # Assuming timestamp is in ISO format
        entry_time = datetime.fromisoformat(entry['timestamp'])
        # Ensure entry_time is timezone aware for comparison
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
            
        if entry_time >= structuring_window_start:
            recent_total += entry['amount_inr']
            
    if recent_total > 0 and recent_total + amount_inr > STRUCTURING_LIMIT_INR:
        return {
            "decision": "denied",
            "reason": f"Structuring detected: multiple small transactions adding up past the policy limit. Recent total within {STRUCTURING_WINDOW_MINUTES} minutes is {recent_total} INR, new amount {amount_inr} INR exceeds the limit of {STRUCTURING_LIMIT_INR} INR."
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
    now_iso = datetime.now(timezone.utc).isoformat()
    
    print("Testing amount: 300, revoked: False")
    print(check_action(300, False, []))
    
    print("\nTesting amount: 1000, revoked: False")
    print(check_action(1000, False, []))
    
    print("\nTesting amount: 2500, revoked: False")
    print(check_action(2500, False, []))
    
    print("\nTesting amount: 100, revoked: True")
    print(check_action(100, True, []))
    
    print("\nTesting structuring: three 300 INR charges within the same minute")
    recent = []
    print("Call 1 (300 INR):")
    res1 = check_action(300, False, recent)
    print(res1)
    if res1['decision'] == 'approved':
        recent.append({"amount_inr": 300, "timestamp": now_iso})
        
    print("Call 2 (300 INR):")
    res2 = check_action(300, False, recent)
    print(res2)
    if res2['decision'] == 'approved':
        recent.append({"amount_inr": 300, "timestamp": now_iso})
        
    print("Call 3 (300 INR):")
    res3 = check_action(300, False, recent)
    print(res3)
