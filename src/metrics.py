import json
import os

METRICS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "metrics.json")

def _load_metrics() -> dict:
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {
        "total_orders": 0,
        "total_revenue_inr": 0.0,
        "total_upsell_orders": 0,
        "total_upsell_revenue_inr": 0.0,
        "total_upsell_offers_shown": 0
    }

def _save_metrics(metrics: dict):
    os.makedirs(os.path.dirname(METRICS_PATH), exist_ok=True)
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

def record_order(amount_inr: float, is_upsell: bool):
    metrics = _load_metrics()
    metrics["total_orders"] += 1
    metrics["total_revenue_inr"] += amount_inr
    if is_upsell:
        metrics["total_upsell_orders"] += 1
        metrics["total_upsell_revenue_inr"] += amount_inr
    _save_metrics(metrics)

def record_upsell_offered():
    metrics = _load_metrics()
    metrics["total_upsell_offers_shown"] += 1
    _save_metrics(metrics)

def get_summary() -> dict:
    metrics = _load_metrics()
    total_orders = metrics.get("total_orders", 0)
    total_revenue_inr = metrics.get("total_revenue_inr", 0.0)
    upsell_offers_shown = metrics.get("total_upsell_offers_shown", 0)
    upsell_orders = metrics.get("total_upsell_orders", 0)
    
    upsell_acceptance_rate = 0.0
    if upsell_offers_shown > 0:
        upsell_acceptance_rate = upsell_orders / upsell_offers_shown

    average_order_value_inr = 0.0
    if total_orders > 0:
        average_order_value_inr = total_revenue_inr / total_orders

    return {
        "total_orders": total_orders,
        "total_revenue_inr": total_revenue_inr,
        "upsell_offers_shown": upsell_offers_shown,
        "upsell_orders": upsell_orders,
        "upsell_acceptance_rate": upsell_acceptance_rate,
        "average_order_value_inr": average_order_value_inr
    }
