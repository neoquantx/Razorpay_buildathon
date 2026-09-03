"""Utility script to summarize and display business metrics."""
import metrics

def main():
    summary = metrics.get_summary()
    orders = summary["total_orders"]
    upsells_accepted = summary["upsell_orders"]
    upsells_offered = summary["upsell_offers_shown"]
    acceptance_rate = summary["upsell_acceptance_rate"] * 100
    avg_order_value = summary["average_order_value_inr"]
    
    print(f"Orders: {orders}, Upsells accepted: {upsells_accepted} of {upsells_offered} offered ({acceptance_rate:.1f}%), Average order value: ₹{avg_order_value:.2f}")

if __name__ == "__main__":
    main()
