import asyncio
from typing import Dict, List, Callable, Any, Awaitable

class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], Awaitable[None]]]] = {}

    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    async def publish(self, event_type: str, payload: Dict[str, Any]):
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                asyncio.create_task(self._safe_call(callback, event_type, payload))

    async def _safe_call(self, callback, event_type: str, payload: Dict[str, Any]):
        try:
            await callback(payload)
        except Exception as e:
            print(f"[dex_events] subscriber error on {event_type}: {e}")

# Global event bus singleton
bus = EventBus()
