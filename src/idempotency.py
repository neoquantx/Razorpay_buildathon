import json
import os
import hashlib
from datetime import datetime, timezone

IDEMPOTENCY_STORE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'idempotency_store.json')

def _load_store() -> dict:
    if not os.path.exists(IDEMPOTENCY_STORE_PATH):
        return {}
    try:
        with open(IDEMPOTENCY_STORE_PATH, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def _save_store(store: dict):
    os.makedirs(os.path.dirname(IDEMPOTENCY_STORE_PATH), exist_ok=True)
    with open(IDEMPOTENCY_STORE_PATH, 'w') as f:
        json.dump(store, f, indent=2)

def get_cached_result(key: str) -> dict | None:
    store = _load_store()
    return store.get(key)

def save_result(key: str, result: dict):
    store = _load_store()
    store[key] = result
    _save_store(store)

def generate_key(amount_inr: float, item_description: str) -> str:
    """
    Generate a stable key based on amount, description, and the current minute.
    """
    now = datetime.now(timezone.utc)
    current_minute_str = now.strftime("%Y-%m-%d %H:%M")
    
    raw_key = f"{amount_inr}:{item_description}:{current_minute_str}"
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
