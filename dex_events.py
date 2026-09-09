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
                asyncio.create_task(callback(payload))

# Global event bus singleton
bus = EventBus()
