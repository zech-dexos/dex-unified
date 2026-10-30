"""Focused tests for DexOS event delivery guarantees."""
import asyncio
import unittest

from dex_events import EventBus


class EventBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_waits_and_preserves_registration_order(self):
        bus = EventBus()
        observed = []

        async def first(payload):
            await asyncio.sleep(0)
            observed.append(("first", payload["event_id"]))

        def second(payload):
            observed.append(("second", payload["event_id"]))

        bus.subscribe("INTERACTION", first)
        bus.subscribe("INTERACTION", first)
        bus.subscribe("INTERACTION", second)

        outcomes = await bus.publish("INTERACTION", {"event_id": "event-1"})

        self.assertEqual(
            observed,
            [("first", "event-1"), ("second", "event-1")],
        )
        self.assertEqual([item["status"] for item in outcomes], ["completed", "completed"])

    async def test_subscriber_failure_does_not_skip_later_layers(self):
        bus = EventBus()
        observed = []

        async def failing(_payload):
            raise RuntimeError("expected test failure")

        async def following(payload):
            observed.append(payload["event_id"])

        bus.subscribe("INTERACTION", failing)
        bus.subscribe("INTERACTION", following)

        outcomes = await bus.publish("INTERACTION", {"event_id": "event-2"})

        self.assertEqual(observed, ["event-2"])
        self.assertEqual([item["status"] for item in outcomes], ["failed", "completed"])
        self.assertIn("expected test failure", outcomes[0]["error"])


if __name__ == "__main__":
    unittest.main()
