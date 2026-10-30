import asyncio
import json
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

    def test_two_os_processes_exchange_and_ack_events(self):
        import subprocess
        import sys

        event = {
            "event_id": "interaction-1",
            "message": "Root's event",
        }
        publisher = """
import asyncio
from dex_events import EventBus
asyncio.run(EventBus().publish("PARTICIPANT_EVENT", {
    "event_id": "interaction-1",
    "message": "Root's event",
}))
"""
        consumer = """
import asyncio
import json
from dex_events import EventBus
bus = EventBus()
received = []
async def handler(payload):
    received.append(payload["event_id"])
bus.subscribe("PARTICIPANT_EVENT", handler)
result = asyncio.run(bus.drain_shared())
print(json.dumps({"result": result, "received": received}))
"""
        env = dict(os.environ, DEX_EVENT_BRIDGE_PATH=self.db)
        publisher_env = dict(env, DEX_EVENT_CONSUMER="api")
        consumer_env = dict(env, DEX_EVENT_CONSUMER="ambient")

        subprocess.run(
            [sys.executable, "-c", publisher],
            check=True,
            env=publisher_env,
            capture_output=True,
            text=True,
        )
        first = subprocess.run(
            [sys.executable, "-c", consumer],
            check=True,
            env=consumer_env,
            capture_output=True,
            text=True,
        )
        result = json.loads(first.stdout.strip().splitlines()[-1])
        self.assertEqual(result["result"]["received"], 1)
        self.assertEqual(result["result"]["acknowledged"], 1)
        self.assertEqual(result["received"], [event["event_id"]])

        second = subprocess.run(
            [sys.executable, "-c", consumer],
            check=True,
            env=consumer_env,
            capture_output=True,
            text=True,
        )
        replay = json.loads(second.stdout.strip().splitlines()[-1])
        self.assertEqual(replay["result"]["received"], 0)
        self.assertEqual(replay["received"], [])

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
