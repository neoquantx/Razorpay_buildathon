"""
multi_merchant.py — Multi-merchant catalog loader, price comparison, and purchase.

Pure business logic, no Gemini dependency. Reuses the same guardrail, payment,
audit_log, idempotency, and session_state modules as the rest of the project.
"""

import json
import os
from datetime import datetime, timezone

import guardrail
import payment
import audit_log
import idempotency
import session_state as ss_module  # avoid name collision with the dict param

# ── Merchant registry ─────────────────────────────────────────────────
MERCHANTS = {
    "urban_threads": "Urban Threads",
    "trail_supply":  "Trail Supply Co",
    "value_mart":    "Value Mart",
}

_MERCHANTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'config', 'merchants')


# ── Catalog helpers ───────────────────────────────────────────────────
def get_merchant_catalog(merchant_id: str) -> dict:
    """Load and return the full catalog for *merchant_id*.

    Raises ValueError if the merchant_id is not in MERCHANTS.
    Raises FileNotFoundError if the JSON file is missing on disk.
    """
    if merchant_id not in MERCHANTS:
        raise ValueError(
            f"Unknown merchant_id '{merchant_id}'. "
            f"Valid IDs: {', '.join(sorted(MERCHANTS))}"
        )
    path = os.path.join(_MERCHANTS_DIR, f"{merchant_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Catalog file not found: {path}")
    with open(path, 'r') as f:
        return json.load(f)


# ── Price comparison ──────────────────────────────────────────────────
def find_cheapest(item_name: str) -> dict:
    """Check every merchant's catalog for *item_name* (case-insensitive).

    Returns a dict with keys:
        item, comparison (list sorted cheapest-first; not-found last),
        cheapest_merchant_id, cheapest_price_inr
    or a not-found result if no merchant carries the item.
    """
    item_lower = item_name.lower()
    comparison = []

    for mid, display_name in MERCHANTS.items():
        try:
            catalog = get_merchant_catalog(mid)
        except FileNotFoundError:
            comparison.append({
                "merchant_id": mid,
                "merchant_name": display_name,
                "price_inr": None,
                "found": False,
            })
            continue

        # Case-insensitive lookup
        matched_price = None
        for key in catalog:
            if key.lower() == item_lower:
                matched_price = catalog[key]["price_inr"]
                break

        comparison.append({
            "merchant_id": mid,
            "merchant_name": display_name,
            "price_inr": matched_price,
            "found": matched_price is not None,
        })

    # Sort: found items by price ascending, not-found items last
    comparison.sort(key=lambda e: (not e["found"], e["price_inr"] if e["found"] else float('inf')))

    # Identify cheapest
    found_entries = [e for e in comparison if e["found"]]
    if not found_entries:
        return {
            "item": item_name,
            "comparison": comparison,
            "cheapest_merchant_id": None,
            "cheapest_price_inr": None,
            "status": "not_found_anywhere",
            "message": f"No merchant currently stocks '{item_name}'.",
        }

    cheapest = found_entries[0]
    return {
        "item": item_name,
        "comparison": comparison,
        "cheapest_merchant_id": cheapest["merchant_id"],
        "cheapest_price_inr": cheapest["price_inr"],
    }


# ── Purchase from a specific merchant ────────────────────────────────
def buy_from_merchant(
    merchant_id: str,
    item_name: str,
    quantity: int,
    session_state: dict,
) -> dict:
    """Buy *quantity* × *item_name* from *merchant_id*.

    Mirrors the create_payment handler in agent.py:
    1. Authoritative price from the merchant's own catalog (never trust caller).
    2. Guardrail check.
    3. Idempotent payment creation.
    4. Audit log with merchant-specific action name.
    5. session_state update (recent_amounts).

    Returns a result dict with at least a 'status' key.
    """
    # ── 1. Load authoritative price ──
    try:
        catalog = get_merchant_catalog(merchant_id)
    except (ValueError, FileNotFoundError) as exc:
        return {"status": "error", "message": str(exc)}

    item_lower = item_name.lower()
    matched_key = None
    for key in catalog:
        if key.lower() == item_lower:
            matched_key = key
            break

    if matched_key is None:
        return {"status": "error", "message": f"'{item_name}' not found in {MERCHANTS.get(merchant_id, merchant_id)}'s catalog."}

    price_inr = catalog[matched_key]["price_inr"]
    total_inr = price_inr * quantity
    action_name = f"shopper_buy_{merchant_id}"

    # ── 2. Guardrail ──
    revoked = session_state.get("revoked", False)
    recent_amounts = session_state.get("recent_amounts", [])
    decision_result = guardrail.check_action(total_inr, revoked, recent_amounts)
    decision = decision_result["decision"]
    reason = decision_result["reason"]

    if decision == "denied":
        audit_log.log_action(action_name, total_inr, reason, "denied")
        return {"status": "denied", "reason": reason}

    if decision == "needs_confirmation":
        audit_log.log_action(action_name, total_inr, reason, "needs_confirmation")
        return {"status": "needs_confirmation", "reason": reason, "total_inr": total_inr}

    # ── 3. Approved → create payment ──
    now = datetime.now(timezone.utc).isoformat()
    description = f"{quantity}x {matched_key} from {MERCHANTS[merchant_id]}"

    try:
        key = idempotency.generate_key(total_inr, description)
        cached = idempotency.get_cached_result(key)
        if cached:
            order = cached.get("order")
        else:
            order = payment.create_order(total_inr, description, idempotency_key=key)
            idempotency.save_result(key, {"order": order})

        audit_log.log_action(action_name, total_inr, reason, "approved")

        # ── 4. Update session_state ──
        recent_amounts.append({"amount_inr": total_inr, "timestamp": now})
        session_state["recent_amounts"] = recent_amounts
        ss_module.save_state(session_state)

        order_id = order.get("order_id") if isinstance(order, dict) else order
        return {
            "status": "success",
            "order_id": order_id,
            "amount_inr": total_inr,
            "merchant_id": merchant_id,
            "merchant_name": MERCHANTS[merchant_id],
            "item": matched_key,
            "quantity": quantity,
        }
    except payment.PaymentFailedError as exc:
        audit_log.log_action(action_name, total_inr, str(exc), "failed")
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:
        audit_log.log_action(action_name, total_inr, str(exc), "failed")
        return {"status": "error", "error": str(exc)}
