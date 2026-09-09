from typing import Dict, Any
from self_state import load_self_state

class DexState:
    def __init__(self):
        # Initial load from persistent self-state
        try:
            self._state = load_self_state()
        except Exception as e:
            print(f"[dex_state] self_state load failed: {e}")
            self._state = {}

    def get_state(self) -> Dict[str, Any]:
        """Returns the canonical shared runtime state."""
        return self._state

    def update_state(self, key: str, value: Any):
        """Updates a portion of the shared state."""
        self._state[key] = value

    def refresh(self):
        """Refresh from durable storage if needed."""
        try:
            self._state = load_self_state()
        except Exception as e:
            print(f"[dex_state] refresh failed: {e}")

# Global canonical shared state
shared_state = DexState()
