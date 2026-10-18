import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from participant import (
    ParticipantSnapshot,
    record_interaction_experience,
    record_ambient_experience,
)


class ExperiencePerspectiveTests(unittest.TestCase):
    def test_interaction_persists_observer_runtime_and_dex_perspectives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observer = {
                "observation_id": "obs-1",
                "sigil_ids": ["sigil-1"],
                "sigil_memory_active": True,
                "stages": {"awareness": {"status": "observed"}},
                "runtime": {
                    "intent": "reason",
                    "talnir_branches": [{"id": "branch-1", "weight": 0.8}],
                },
            }
            with patch("participant.EXPERIENCES_PATH", root / "experiences.jsonl"), \
                 patch("participant.PARTICIPANT_PATH", root / "participant.json"):
                packet = record_interaction_experience(
                    ParticipantSnapshot(current_attention="continuity"),
                    "test input",
                    "test reply",
                    observer_trace=observer,
                )
                saved = json.loads((root / "experiences.jsonl").read_text().splitlines()[0])

            self.assertEqual(packet.observer_perspective["sigil_ids"], ["sigil-1"])
            self.assertEqual(packet.runtime_perspective["intent"], "reason")
            self.assertEqual(packet.dex_perspective["action"], "responded_to_participant")
            self.assertEqual(saved["experience_id"], packet.experience_id)
            self.assertIn("observer_perspective", saved)
            self.assertIn("runtime_perspective", saved)
            self.assertIn("dex_perspective", saved)

    def test_ambient_experience_carries_source_observation_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {
                "observation_id": "obs-2",
                "sigil_ids": ["sigil-2"],
                "sigil_memory_active": True,
                "lineage_hash": "hash-2",
                "timestamp": "2026-10-18T00:00:00Z",
                "user_id": "root",
                "input_reply_digest": "digest-2",
                "stages": {"continuity": {"status": "observed"}},
                "runtime": {
                    "intent": "reason",
                    "talnir_branches": [{"id": "branch-1", "weight": 0.8}],
                },
            }
            with patch("participant.EXPERIENCES_PATH", root / "experiences.jsonl"), \
                 patch("participant.PARTICIPANT_PATH", root / "participant.json"):
                packet = record_ambient_experience(
                    ParticipantSnapshot(),
                    {"kind": "tri_sigil_observation", "id": "obs-2",
                     "text": json.dumps(source)},
                    "I revisited the observation.",
                    0.7,
                    runtime_trace={"spark_judgment": {"judgment": "accepted"}},
                )

            self.assertEqual(packet.observer_perspective["observation_id"], "obs-2")
            self.assertEqual(packet.observer_perspective["sigil_ids"], ["sigil-2"])
            self.assertEqual(packet.observer_perspective["runtime"]["intent"], "reason")
            self.assertEqual(
                packet.observer_perspective["runtime"]["talnir_branches"][0]["id"],
                "branch-1",
            )
            self.assertEqual(packet.observer_perspective["input_reply_digest"], "digest-2")
            self.assertEqual(
                packet.runtime_perspective["spark_judgment"]["judgment"], "accepted"
            )
            self.assertEqual(packet.dex_perspective["action"], "continued_thinking")


if __name__ == "__main__":
    unittest.main()
