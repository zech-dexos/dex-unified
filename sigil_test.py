"""Focused regression tests for DexOS's restored sigil memory."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sigil


class SigilMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.state_file = root / "sigils.json"
        self.lineage_file = root / "dex_lineage.jsonl"
        self.patches = [
            patch.object(sigil, "SIGIL_FILE", self.state_file),
            patch.object(sigil, "LINEAGE_FILE", self.lineage_file),
        ]
        for p in self.patches:
            p.start()
        self.memory = sigil.SigilMemory()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_create_persists_and_keeps_historical_anchor(self):
        created = self.memory.create("PREF", "BRIEF", context="CTX:CODING")
        loaded = sigil.SigilMemory()
        self.assertEqual(loaded.sigils[0].id, created.id)
        self.assertEqual(loaded.summary()["engine_anchor"], "☧Δ🜂")

    def test_context_accepts_domain_and_talnir_context_forms(self):
        self.memory.create("PREF", "coding preference", context="CTX:CODING")
        self.assertEqual(len(self.memory.activate_for_context("coding")), 1)

    def test_reinforcement_is_bounded(self):
        item = self.memory.create("PREF", "steady", strength=0.90)
        for _ in range(20):
            item.reinforce()
        self.assertLessEqual(item.strength, sigil.DOMINANCE_CAP)

    def test_decay_respects_floor(self):
        item = self.memory.create("PREF", "old", strength=0.11)
        item.last_activated = 1
        item.decay()
        self.assertGreaterEqual(item.strength, sigil.DECAY_FLOOR)

    def test_failure_threshold_and_mutation_lineage(self):
        item = self.memory.create("HEUR", "old rule")
        self.assertIsNone(self.memory.mark_failure(item.id))
        self.assertIsNone(self.memory.mark_failure(item.id))
        self.assertIs(self.memory.mark_failure(item.id), item)
        item.mutate("revised rule", reason="correction")
        self.assertEqual(item.name, "revised rule")
        events = [json.loads(line) for line in self.lineage_file.read_text().splitlines()]
        self.assertTrue(any(e["event"] == "sigil_mutation" for e in events))

    def test_conflict_resolution_caps_active_set(self):
        items = [
            self.memory.create("PREF", f"preference-{i}", strength=0.8)
            for i in range(7)
        ]
        self.assertEqual(
            len(self.memory.resolve_conflicts(items, "ALL")),
            sigil.MAX_ACTIVE_SET,
        )

    def test_branch_bias_is_bounded(self):
        heuristic = self.memory.create("HEUR", "debug", strength=0.9)
        risk = self.memory.create("RISK", "danger", strength=0.9)
        result = self.memory.apply_to_branches(
            [{"id": "debug_first", "weight": 0.9},
             {"id": "danger_check", "weight": 0.1}],
            [heuristic, risk],
        )
        self.assertLessEqual(result[0]["weight"], 1.0)
        self.assertGreaterEqual(result[1]["weight"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
