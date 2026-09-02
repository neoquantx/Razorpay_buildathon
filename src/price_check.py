"""
price_check.py — Standalone price-integrity validator.

No Gemini / SDK dependencies; importable and testable in any environment.
Called by agent.py before the guardrail, and directly by the test suite.
"""

import json
import os

_PRODUCTS_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'products.json')


def _load_products() -> dict:
    """Return the product catalog; empty dict if the file is missing."""
    if not os.path.exists(_PRODUCTS_PATH):
        return {}
    with open(_PRODUCTS_PATH, 'r') as f:
        return json.load(f)


def verify_item_price(item_name: str, amount_inr: float, session_state: dict) -> dict:
    """
    Validate amount_inr for item_name before a payment is created.

    Returns {"ok": True} when the price is acceptable, or
    {"ok": False, "reason": "..."} when it must be denied.

    Rules (applied in order):
    1. Case-insensitive substring match against products.json.
       - If NO match: return {"ok": True}.
         Scope limitation: items outside the fixed catalog are not covered
         by this check; the guardrail spending limits still apply to them.
    2. If amount_inr exactly equals the catalog price: {"ok": True}.
    3. Check session_state["last_negotiation"] — set by the negotiate_price
       handler when the decision is "accepted" or "countered".
       If it matches this item_name (case-insensitive) AND amount_inr equals
       its final_price_inr: {"ok": True} (legitimately negotiated price).
    4. Otherwise: {"ok": False, "reason": "Price mismatch — ..."}.
    """
    catalog = _load_products()

    # Find catalog entry via case-insensitive substring match
    catalog_price = None
    matched_key = None
    item_lower = item_name.lower()
    for key, product in catalog.items():
        if key.lower() in item_lower or item_lower in key.lower():
            catalog_price = product["price_inr"]
            matched_key = key
            break

    # Scope limitation: unknown items are not covered by this check
    if matched_key is None:
        return {"ok": True}

    # Exact catalog price — always fine
    if amount_inr == catalog_price:
        return {"ok": True}

    # Check for a legitimately negotiated price
    last_neg = session_state.get("last_negotiation")
    if (
        last_neg is not None
        and last_neg.get("item_name", "").lower() == matched_key.lower()
        and amount_inr == last_neg.get("final_price_inr")
    ):
        return {"ok": True}

    return {
        "ok": False,
        "reason": (
            f"Price mismatch — {matched_key} is listed at \u20b9{catalog_price}; "
            f"\u20b9{amount_inr} doesn't match the catalog price or any negotiated "
            f"price for this item. Ask to negotiate if you're looking for a discount."
        ),
    }
