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
        tick = 0

        while self._running:
            try:
                tick += 1
                if tick % 30 == 0:
                    shared_state.refresh()
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
