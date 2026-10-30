"""Focused tests for DexOS event delivery guarantees."""
import asyncio
import unittest

from dex_events import EventBus, bus, setup_cognitive_layers, dispatch_complete


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

    async def test_cognitive_layers_register_once_for_each_process(self):
        setup_cognitive_layers()
        first_counts = {name: len(callbacks) for name, callbacks in bus._subscribers.items()}
        setup_cognitive_layers()
        second_counts = {name: len(callbacks) for name, callbacks in bus._subscribers.items()}

        self.assertEqual(first_counts, second_counts)
        self.assertIn("process_continuity_event", [
            callback.__name__ for callback in bus._subscribers["RESPONSE_COMPLETED"]
        ])
        self.assertIn("process_autobiographical_event", [
            callback.__name__ for callback in bus._subscribers["RESPONSE_COMPLETED"]
        ])
        self.assertIn("evaluate_salience", [
            callback.__name__ for callback in bus._subscribers["PARTICIPANT_EVENT"]
        ])
        self.assertIn("activate_workspace", [
            callback.__name__ for callback in bus._subscribers["ATTENTION_CHANGED"]
        ])

        self.assertIn("process_autobiographical_event", [
            callback.__name__ for callback in bus._subscribers["WORKSPACE_ACTIVATED"]
        ])
        self.assertIn("process_autobiographical_event", [
            callback.__name__ for callback in bus._subscribers["TRI_SIGIL_OBSERVED"]
        ])

    async def test_subscriber_result_preserves_nested_layer_outcomes(self):
        bus = EventBus()

        async def nested(_payload):
            return {"event_dispatch_complete": False, "reason": "child failed"}

        bus.subscribe("OUTER", nested)
        outcomes = await bus.publish("OUTER", {"event_id": "outer-1"})

        self.assertEqual(outcomes[0]["status"], "completed")
        self.assertFalse(outcomes[0]["result"]["event_dispatch_complete"])
        self.assertEqual(outcomes[0]["result"]["reason"], "child failed")
        self.assertFalse(dispatch_complete(outcomes, {"nested"}))
        self.assertFalse(dispatch_complete(outcomes, {"missing"}))

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
