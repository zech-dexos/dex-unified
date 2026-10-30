import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dex_event_bridge
from dex_events import EventBus


class DurableBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "bridge.sqlite3")
        self.path_patch = patch.dict(os.environ, {"DEX_EVENT_BRIDGE_PATH": self.db})
        self.path_patch.start()
        # Force the bridge module to use the isolated test database.
        dex_event_bridge.DB_PATH = Path(self.db)

    def tearDown(self):
        self.path_patch.stop()
        self.temp.cleanup()

    def test_two_runtime_buses_exchange_and_ack_events(self):
        async def scenario():
            received = []
            with patch.dict(os.environ, {"DEX_EVENT_CONSUMER": "api"}):
                api = EventBus()
            with patch.dict(os.environ, {"DEX_EVENT_CONSUMER": "ambient"}):
                ambient = EventBus()

            async def ambient_handler(payload):
                received.append(payload["event_id"])

            ambient.subscribe("PARTICIPANT_EVENT", ambient_handler)
            await api.publish("PARTICIPANT_EVENT", {
                "event_id": "interaction-1",
                "message": "Root's event",
            })

            result = await ambient.drain_shared()
            self.assertEqual(result["received"], 1)
            self.assertEqual(result["acknowledged"], 1)
            self.assertEqual(received, ["interaction-1"])
            self.assertEqual(dex_event_bridge.pending_events("ambient"), [])

        asyncio.run(scenario())

    def test_failed_subscriber_is_not_acknowledged_and_can_retry(self):
        async def scenario():
            with patch.dict(os.environ, {"DEX_EVENT_CONSUMER": "api"}):
                api = EventBus()
            with patch.dict(os.environ, {"DEX_EVENT_CONSUMER": "ambient"}):
                ambient = EventBus()

            attempts = {"count": 0}

            async def flaky_handler(payload):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise RuntimeError("temporary persistence failure")

            ambient.subscribe("THOUGHT_GENERATED", flaky_handler)
            await api.publish("THOUGHT_GENERATED", {
                "event_id": "ambient-1",
                "thought": "a connected thought",
            })

            first = await ambient.drain_shared()
            self.assertEqual(first["failed"], 1)
            self.assertEqual(len(dex_event_bridge.pending_events("ambient")), 1)

            second = await ambient.drain_shared()
            self.assertEqual(second["acknowledged"], 1)
            self.assertEqual(attempts["count"], 2)
            self.assertEqual(dex_event_bridge.pending_events("ambient"), [])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
