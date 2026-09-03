"""Audit logging system for tracking payment actions and outcomes."""
import json
import os
from datetime import datetime, timezone

# Ensure the data directory is created relative to project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_FILE = os.path.join(DATA_DIR, "audit_log.jsonl")

def log_action(action: str, amount_inr: float, reason: str, outcome: str):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "amount": amount_inr,
        "reason": reason,
        "outcome": outcome
    }
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def read_all_logs() -> list:
    if not os.path.exists(LOG_FILE):
        return []
        
    logs = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                logs.append(json.loads(line))
    return logs
