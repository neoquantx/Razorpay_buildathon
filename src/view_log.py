import audit_log
from datetime import datetime

def main():
    logs = audit_log.read_all_logs()
    
    if not logs:
        print("No actions logged yet.")
        return
        
    # Print the table header
    print(f"{'Time':<22} | {'Action':<15} | {'Amount (₹)':<12} | {'Outcome':<20} | {'Reason'}")
    print("-" * 110)
    
    for log in logs:
        timestamp_raw = log.get("timestamp", "")
        
        if timestamp_raw:
            try:
                # Attempt to parse and format the ISO timestamp cleanly
                ts_obj = datetime.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
                time_str = ts_obj.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                # Fallback to just truncating the ISO string
                time_str = timestamp_raw[:19].replace("T", " ")
        else:
            time_str = "N/A"
            
        action = log.get("action", "N/A")
        amount = log.get("amount", 0.0)
        outcome = log.get("outcome", "N/A")
        reason = log.get("reason", "N/A")
        
        # Format the amount properly
        if isinstance(amount, (int, float)):
            amount_str = f"{amount:.2f}"
        else:
            amount_str = str(amount)
            
        print(f"{time_str:<22} | {action:<15} | {amount_str:<12} | {outcome:<20} | {reason}")

if __name__ == "__main__":
    main()
