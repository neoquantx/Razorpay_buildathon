import sys
import os
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import session_state

class TestSessionState(unittest.TestCase):
    def test_persistence(self):
        # 1. Get initial state
        state = session_state.get_state()
        
        # 2. Modify state with a unique marker to verify persistence
        import time
        marker = f"test_marker_{time.time()}"
        state["revoked"] = True
        state["recent_amounts"].append({"amount_inr": 123.45, "timestamp": marker})
        
        # 3. Save state
        session_state.save_state(state)
        
        # 4. Reload state fresh to simulate a restart
        new_state = session_state.get_state()
        
        # 5. Assert values match
        self.assertTrue(new_state["revoked"])
        
        # Check if our marker is in the recent amounts
        found = any(entry.get("timestamp") == marker for entry in new_state["recent_amounts"])
        self.assertTrue(found, "The appended transaction should be loaded from the persisted file.")

if __name__ == '__main__':
    unittest.main()
