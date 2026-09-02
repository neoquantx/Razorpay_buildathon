import json
import os

# ---------------------------------------------------------------------------
# Load policy.json at module startup — same pattern as guardrail.py
# ---------------------------------------------------------------------------
POLICY_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'policy.json')

try:
    with open(POLICY_PATH, 'r') as _f:
        _policy = json.load(_f)
        NEGOTIATION_FLOOR_PCT = _policy['negotiation_floor_pct']
        MIN_AMOUNT_INR = _policy.get('min_amount_inr', 1)
except FileNotFoundError:
    raise RuntimeError(f"Policy file not found at {POLICY_PATH}")
except (json.JSONDecodeError, KeyError) as e:
    raise RuntimeError(f"Policy file is malformed: {e}")


def evaluate_negotiation(catalog_price_inr: float, requested_price_inr: float) -> dict:
    """
    Deterministically decide whether a requested price is acceptable.

    Returns a dict with at least a ``decision`` key. The AI model must relay
    exactly what this function returns — it must never invent or modify the
    discount decision.

    Decisions:
        - "rejected"            – requested price is below the minimum valid amount.
        - "no_discount_needed"  – requested price is at or above catalog price.
        - "accepted"            – within the merchant's negotiation floor.
        - "countered"           – below the floor; best offer is the floor price.
    """
    if requested_price_inr < MIN_AMOUNT_INR:
        return {
            "decision": "rejected",
            "reason": "Invalid requested price.",
        }

    if requested_price_inr >= catalog_price_inr:
        return {
            "decision": "no_discount_needed",
            "final_price_inr": catalog_price_inr,
            "reason": "The catalog price is already at or below what was requested.",
        }

    min_acceptable = catalog_price_inr * (1 - NEGOTIATION_FLOOR_PCT / 100)

    if requested_price_inr >= min_acceptable:
        return {
            "decision": "accepted",
            "final_price_inr": requested_price_inr,
            "reason": f"Within the merchant's {NEGOTIATION_FLOOR_PCT}% negotiation policy.",
        }

    return {
        "decision": "countered",
        "final_price_inr": round(min_acceptable, 2),
        "reason": "Can't go below the policy floor for this item.",
    }


# ---------------------------------------------------------------------------
# Quick smoke-test when run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    examples = [
        # (catalog_price, requested_price, label)
        (1000.0, 950.0,   "within floor (accepted)"),
        (1000.0, 800.0,   "below floor  (countered)"),
        (1000.0, 1000.0,  "at catalog   (no_discount_needed)"),
        (1000.0, 1100.0,  "above catalog (no_discount_needed)"),
        (1000.0, 0.0,     "zero price   (rejected)"),
        (1000.0, -50.0,   "negative     (rejected)"),
    ]

    for catalog, requested, label in examples:
        result = evaluate_negotiation(catalog, requested)
        print(f"{label}: evaluate_negotiation({catalog}, {requested}) -> {result}")
