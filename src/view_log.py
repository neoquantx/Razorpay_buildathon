"""Utility script to format and display the audit log."""
import audit_log
from datetime import datetime
import textwrap

# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"

def print_separator():
    print(f"{DIM}+{'-'*22}+{'-'*18}+{'-'*12}+{'-'*25}+{'-'*50}+{RESET}")

def main():
    logs = audit_log.read_all_logs()
    
    if not logs:
        print(f"{YELLOW}No actions logged yet.{RESET}")
        return
        
    print(f"\n{BOLD}{CYAN}🏦 Razorpay Checkout Agent - Audit Log{RESET}\n")
    print_separator()
    print(f"{DIM}|{RESET} {BOLD}{'Timestamp':<20}{RESET} {DIM}|{RESET} {BOLD}{'Action':<16}{RESET} {DIM}|{RESET} {BOLD}{'Amount (₹)':<10}{RESET} {DIM}|{RESET} {BOLD}{'Status':<23}{RESET} {DIM}|{RESET} {BOLD}{'Reason':<48}{RESET} {DIM}|{RESET}")
    print_separator()
    
    for log in logs:
        # 1. Format Timestamp
        timestamp_raw = log.get("timestamp", "")
        if timestamp_raw:
            try:
                ts_obj = datetime.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
                time_str = ts_obj.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                time_str = timestamp_raw[:19].replace("T", " ")
        else:
            time_str = "N/A"
            
        # 2. Format Action
        action = str(log.get("action", "N/A"))
        
        # 3. Format Amount
        amount = log.get("amount", 0.0)
        amount_str = f"{amount:.2f}" if isinstance(amount, (int, float)) else str(amount)
            
        # 4. Format Status
        outcome = str(log.get("outcome", "N/A")).upper()
        if "APPROVED" in outcome or "SUCCESS" in outcome:
            status_color = GREEN
        elif "FAILED" in outcome or "DENIED" in outcome:
            status_color = RED
        elif "PENDING" in outcome or "CANCELLED" in outcome:
            status_color = YELLOW
        else:
            status_color = BLUE
            
        # 5. Format and wrap Reason
        reason = str(log.get("reason", "N/A"))
        reason_lines = textwrap.wrap(reason, width=48)
        if not reason_lines:
            reason_lines = [""]
            
        # Print the first line
        print(f"{DIM}|{RESET} {CYAN}{time_str:<20}{RESET} {DIM}|{RESET} {MAGENTA}{action:<16}{RESET} {DIM}|{RESET} {GREEN}{amount_str:>10}{RESET} {DIM}|{RESET} {BOLD}{status_color}{outcome:<23}{RESET} {DIM}|{RESET} {reason_lines[0]:<48} {DIM}|{RESET}")
        
        # Print subsequent lines for long reasons
        for line in reason_lines[1:]:
            print(f"{DIM}|{RESET} {'':<20} {DIM}|{RESET} {'':<16} {DIM}|{RESET} {'':>10} {DIM}|{RESET} {'':<23} {DIM}|{RESET} {line:<48} {DIM}|{RESET}")
            
    print_separator()
    print()

if __name__ == "__main__":
    main()
