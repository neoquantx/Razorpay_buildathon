import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

LOG_FILE = os.path.join(DATA_DIR, "audit_log.jsonl")
SESSION_FILE = os.path.join(DATA_DIR, "session_state.json")
METRICS_FILE = os.path.join(DATA_DIR, "metrics.json")
IDEMPOTENCY_FILE = os.path.join(DATA_DIR, "idempotency_store.json")

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # 1. Clear audit_log.jsonl
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        pass
        
    # 2. Reset session_state.json
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"revoked": False, "recent_amounts": []}, f, indent=2)
        
    # 3. Reset metrics.json
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "total_orders": 0,
            "total_revenue_inr": 0.0,
            "total_upsell_orders": 0,
            "total_upsell_revenue_inr": 0.0,
            "total_upsell_offers_shown": 0
        }, f, indent=2)
        
    # 4. Reset idempotency_store.json
    with open(IDEMPOTENCY_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2)

    print("Reset complete: audit log cleared, session state, metrics, and idempotency store zeroed.")

if __name__ == "__main__":
    main()
