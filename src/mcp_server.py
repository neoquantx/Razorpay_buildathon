import sys
import os
import json
from datetime import datetime, timezone
from mcp.server import MCPServer

# Add src/ to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import guardrail
import payment
import audit_log
import session_state
import idempotency
import metrics

mcp = MCPServer("Merchant Store")

PRODUCTS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "products.json")

def _load_catalog() -> dict:
    """Shared helper to load the product catalog as a dict."""
    if not os.path.exists(PRODUCTS_PATH):
        return {}
    with open(PRODUCTS_PATH, "r") as f:
        return json.load(f)

@mcp.resource("catalog://items")
def get_catalog() -> str:
    """Returns the full contents of the product catalog."""
    return json.dumps(_load_catalog(), indent=2)

@mcp.tool()
def browse_catalog() -> dict:
    """Browse all items currently available for purchase, with prices."""
    return _load_catalog()

@mcp.tool()
def create_purchase(item_name: str, quantity: int = 1) -> dict:
    """
    Purchase an item from the catalog.
    
    Args:
        item_name: The name of the item to purchase.
        quantity: The quantity to purchase (default 1).
    """
    # a. Look up item_name in products.json
    catalog = _load_catalog()
    if not catalog:
        return {"status": "error", "message": "Catalog file not found"}
        
    item_name_lower = item_name.lower()
    matched_key = None
    for key in catalog:
        if key.lower() == item_name_lower:
            matched_key = key
            break
            
    if not matched_key:
        return {"status": "error", "message": "Item not found in catalog"}
        
    product = catalog[matched_key]
    price_inr = product["price_inr"]
    
    # b. Compute total_inr
    total_inr = price_inr * quantity
    
    # c. Load current state
    state = session_state.get_state()
    revoked = state.get("revoked", False)
    recent_amounts = state.get("recent_amounts", [])
    
    # d. Call guardrail check
    decision_result = guardrail.check_action(total_inr, revoked, recent_amounts)
    decision = decision_result["decision"]
    reason = decision_result["reason"]
    
    # e. If denied or needs_confirmation
    if decision in ["denied", "needs_confirmation"]:
        audit_log.log_action("mcp_create_purchase", total_inr, reason, decision)
        return {"status": decision, "reason": reason}
        
    # f. If approved
    try:
        idempotency_key = idempotency.generate_key(total_inr, matched_key)
        cached = idempotency.get_cached_result(idempotency_key)
        
        if cached:
            order = cached.get("order")
        else:
            order = payment.create_order(total_inr, f"{quantity}x {matched_key}", idempotency_key=idempotency_key)
            idempotency.save_result(idempotency_key, {"order": order})
            
        audit_log.log_action("mcp_create_purchase", total_inr, reason, "approved")
        
        # update recent_amounts
        now = datetime.now(timezone.utc).isoformat()
        recent_amounts.append({"amount_inr": total_inr, "timestamp": now})
        state["recent_amounts"] = recent_amounts
        session_state.save_state(state)
        
        # record metrics
        metrics.record_order(total_inr, is_upsell=False)
        
        order_id = order.get("order_id") if isinstance(order, dict) else order
        return {
            "status": "success",
            "order_id": order_id,
            "amount_inr": total_inr,
            "item": matched_key,
            "quantity": quantity
        }
    except Exception as e:
        audit_log.log_action("mcp_create_purchase", total_inr, str(e), "failed")
        return {"status": "failed", "error": str(e)}

if __name__ == "__main__":
    mcp.run()
