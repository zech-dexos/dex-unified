import asyncio
from dex_events import bus
from dex_state import shared_state

class DexSubstrate:
    def __init__(self):
        self._running = False

    async def run_substrate_loop(self):
        """
        The pulse maintains the continuous living operation of Dex.
        It is extremely lightweight and keeps the shared state fabric flowing.
        """
        print("[Substrate] Starting continuous substrate loop...")
        self._running = True

        while self._running:
            try:
                # Maintain the heartbeat of the system.
                # Lightweight substrate operations can inspect state here.
                # E.g., tick processes, detect changes, or trigger internal events.

                # Simply sleeping for a minimal tick interval (e.g., 1 second)
                # allows the background loop to maintain continuous flow without blocking.
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                print("[Substrate] Loop cancelled, shutting down")
                self._running = False
                break
            except Exception as e:
                print(f"[Substrate] Unexpected error: {e}")
                await asyncio.sleep(5.0)

# The continuous substrate instance
substrate = DexSubstrate()

async def run_substrate_loop():
    await substrate.run_substrate_loop()
