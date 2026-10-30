"""DexOS event fabric.

Events are the integration boundary between the live runtime and persistent
cognitive subsystems. Publishing an event is a completion barrier: all
registered subscribers are invoked in registration order and awaited before
publish returns. This keeps the existing event API while ensuring that a
completed response cannot outrun its continuity/autobiography handlers.

Subscribers should remain bounded, deterministic persistence/coordination
handlers. Long-running inference belongs in the ambient scheduler, not in a
request-completion subscriber.
"""
import inspect
from typing import Dict, List, Callable, Any, Awaitable


class EventBus:
    def __init__(self):
        self._subscribers: Dict[
            str, List[Callable[[Dict[str, Any]], Awaitable[None]]]
        ] = {}

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Register a subscriber once, preserving deterministic registration order."""
        subscribers = self._subscribers.setdefault(event_type, [])
        if callback not in subscribers:
            subscribers.append(callback)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> List[dict]:
        """Deliver an event and wait for each subscriber to finish.

        A snapshot prevents subscription changes during delivery from changing
        the current dispatch. One failing subscriber is reported but does not
        prevent later subscribers from receiving the same event.
        """
        outcomes = []
        for callback in tuple(self._subscribers.get(event_type, ())):
            outcomes.append(
                await self._safe_call(callback, event_type, payload)
            )
        return outcomes

    async def _safe_call(
        self,
        callback: Callable[[Dict[str, Any]], Any],
        event_type: str,
        payload: Dict[str, Any],
    ) -> dict:
        name = getattr(callback, "__qualname__", getattr(callback, "__name__", repr(callback)))
        try:
            result = callback(payload)
            if inspect.isawaitable(result):
                await result
            return {"subscriber": name, "status": "completed"}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"[dex_events] subscriber error on {event_type} ({name}): {error}")
            return {
                "subscriber": name,
                "status": "failed",
                "error": error,
            }


# Global event bus singleton
bus = EventBus()
