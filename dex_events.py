"""DexOS event fabric with a durable cross-process integration bridge.

The in-process bus remains the synchronous cognitive dispatch boundary. Each
published event is also appended to a SQLite journal in DEXOS_STATE_DIR. Other
runtime processes consume that journal with independent acknowledgements, so
API and ambient cognition no longer depend on sharing Python memory.

Delivery is at-least-once across process crashes. Subscribers should use the
event_id as an idempotency key when making non-idempotent mutations.
"""
import asyncio
import inspect
import os
import sys
import uuid
from typing import Dict, List, Callable, Any, Awaitable

from dex_event_bridge import append_event, pending_events, acknowledge_event


class EventBus:
    def __init__(self):
        self._subscribers: Dict[
            str, List[Callable[[Dict[str, Any]], Awaitable[None]]]
        ] = {}
        self._bridge_lock = asyncio.Lock()
        self._draining_bridge = False
        self._consumer_id = self._resolve_consumer_id()
        self.last_bridge_result = {"received": 0, "acknowledged": 0, "failed": 0}

    @staticmethod
    def _resolve_consumer_id() -> str:
        configured = os.environ.get("DEX_EVENT_CONSUMER", "").strip()
        if configured:
            return configured
        command = os.path.basename(sys.argv[0]).lower()
        if "ambient" in command:
            return "ambient"
        if "uvicorn" in command or "api" in command:
            return "api"
        return f"runtime-{os.getpid()}"

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Register a subscriber once, preserving deterministic registration order."""
        subscribers = self._subscribers.setdefault(event_type, [])
        if callback not in subscribers:
            subscribers.append(callback)

    async def _dispatch_local(self, event_type: str, payload: Dict[str, Any]) -> List[dict]:
        """Deliver one shared event to every cognitive layer concurrently.

        Each subscriber receives the same immutable-in-practice event snapshot.
        Results retain registration order even though handlers execute together.
        A slow persistence layer therefore does not prevent another layer from
        observing the event at the same time.
        """
        subscribers = tuple(self._subscribers.get(event_type, ()))
        if not subscribers:
            return []
        return await asyncio.gather(*(
            self._safe_call(callback, event_type, dict(payload))
            for callback in subscribers
        ))

    async def drain_shared(self, limit: int = 64) -> dict:
        """Consume events emitted by the other runtime process.

        Acknowledgements are written only after every local subscriber succeeds.
        Failed deliveries remain pending for retry on the next bus operation.
        """
        if self._draining_bridge:
            return {"received": 0, "acknowledged": 0, "failed": 0}
        async with self._bridge_lock:
            self._draining_bridge = True
            received = acknowledged = failed = 0
            try:
                for event in pending_events(self._consumer_id, limit=limit):
                    received += 1
                    event_type = str(event.get("event_type") or "")
                    payload = event.get("payload")
                    if not event_type or not isinstance(payload, dict):
                        acknowledge_event(self._consumer_id, event["event_id"])
                        acknowledged += 1
                        continue
                    outcomes = await self._dispatch_local(event_type, payload)
                    if all(item.get("status") == "completed" for item in outcomes):
                        acknowledge_event(self._consumer_id, event["event_id"])
                        acknowledged += 1
                    else:
                        failed += 1
                return {
                    "received": received,
                    "acknowledged": acknowledged,
                    "failed": failed,
                }
            finally:
                self._draining_bridge = False

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> List[dict]:
        """Journal an event, drain remote events, then complete local delivery."""
        event = dict(payload or {})
        event_id = str(event.get("event_id") or uuid.uuid4().hex)
        event["event_id"] = event_id
        event.setdefault("event_type", event_type)
        event.setdefault("event_origin", self._consumer_id)
        append_event(event_id, event_type, self._consumer_id, event)

        self.last_bridge_result = await self.drain_shared()
        return await self._dispatch_local(event_type, event)

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
                result = await result
            outcome = {"subscriber": name, "status": "completed"}
            if isinstance(result, dict):
                outcome["result"] = result
            return outcome
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


def setup_cognitive_layers() -> None:
    """Register persistent cognitive layers in each runtime process."""
    from dex_continuity import setup_continuity
    from dex_autobiography import setup_autobiography
    from dex_attention import setup_attention
    from dex_workspace import setup_workspace
    from participant import setup_live_experience_observer

    setup_continuity()
    setup_autobiography()
    setup_attention()
    setup_workspace()
    setup_live_experience_observer()


def dispatch_complete(outcomes, expected_subscribers=()) -> bool:
    """Validate subscriber delivery, including nested layer dispatches."""
    if not isinstance(outcomes, list):
        return False
    names = {
        item.get("subscriber")
        for item in outcomes
        if isinstance(item, dict) and item.get("status") == "completed"
    }
    if not set(expected_subscribers).issubset(names):
        return False
    for item in outcomes:
        if not isinstance(item, dict) or item.get("status") != "completed":
            return False
        result = item.get("result")
        if isinstance(result, dict):
            if result.get("event_dispatch_complete") is False:
                return False
            nested = result.get("event_dispatch")
            if isinstance(nested, list) and not dispatch_complete(nested):
                return False
    return True
