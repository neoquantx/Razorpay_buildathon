import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "data", "audit_log.jsonl")

def main():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            pass
        print("Audit log cleared. Ready for a fresh demo run.")
    else:
        print("No log file found — already clean.")

if __name__ == "__main__":
    main()
