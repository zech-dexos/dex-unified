import asyncio
from dex_events import bus
from dex_state import shared_state


class DexSubstrate:
    """Continuous event/heartbeat fabric. Cognition enters through pulse layers."""

    def __init__(self):
        self._running = False

    async def run_substrate_loop(self):
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

    async def pulse_event(self, event_type: str, payload: dict):
        """Enter an event into the pulse fabric for attention/experience integration."""
        await bus.publish(event_type, {"event_type": event_type, **payload})


substrate = DexSubstrate()


async def run_substrate_loop():
    await substrate.run_substrate_loop()
