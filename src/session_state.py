"""Session state management for tracking active sessions."""
import json
import os

SESSION_STATE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'session_state.json')

def get_state() -> dict:
    if not os.path.exists(SESSION_STATE_PATH):
        initial_state = {"revoked": False, "recent_amounts": []}
        save_state(initial_state)
        return initial_state
        
    with open(SESSION_STATE_PATH, 'r') as f:
        return json.load(f)

def save_state(state: dict):
    os.makedirs(os.path.dirname(SESSION_STATE_PATH), exist_ok=True)
    with open(SESSION_STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)
