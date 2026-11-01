"""Cross-process durability checks for DexOS SelfState."""
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from self_state import _deep_merge, load_self_state, update_self_state


def _append_events(path_text: str, worker: str, count: int) -> None:
    path = Path(path_text)
    for index in range(count):
        state = load_self_state(path)
        events = list(state.get("continuity_events", []) or [])
        events.append({
            "event_id": f"{worker}-{index}",
            "event_type": "TEST_EVENT",
            "summary": f"event from {worker}",
        })
        update_self_state(
            {"continuity_events": events},
            path=path,
            _max_retries=50,
        )


class SelfStateConcurrencyTests(unittest.TestCase):
    def test_stale_record_lists_merge_without_losing_concurrent_additions(self):
        base = {
            "continuity_events": [
                {"event_id": "event-a", "event_type": "TEST", "summary": "original"}
            ]
        }
        stale_delta = {
            "continuity_events": [
                {"event_id": "event-a", "event_type": "TEST", "summary": "updated"},
                {"event_id": "event-b", "event_type": "TEST", "summary": "new"},
            ]
        }
        merged = _deep_merge(base, stale_delta)
        records = merged["continuity_events"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["summary"], "updated")
        self.assertEqual(records[1]["event_id"], "event-b")

    def test_parallel_processes_preserve_all_continuity_events(self):
        with tempfile.TemporaryDirectory(prefix="dex-self-state-") as directory:
            path = Path(directory) / "identity.json"
            load_self_state(path)
            workers = [
                multiprocessing.Process(
                    target=_append_events,
                    args=(str(path), worker, 12),
                )
                for worker in ("api", "ambient", "observer")
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=30)
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
                    self.fail("SelfState writer did not finish within 30 seconds")
                self.assertEqual(worker.exitcode, 0)

            state = load_self_state(path)
            events = state.get("continuity_events", [])
            self.assertEqual(len(events), 36)
            ids = [item["event_id"] for item in events]
            self.assertEqual(len(set(ids)), 36)
            self.assertEqual(state["version"], 36)


if __name__ == "__main__":
    unittest.main()
