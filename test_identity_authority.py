"""Regression tests for constitutional authority and cognitive-state preservation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import boot


class IdentityAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.constitution_path = self.root / "identity_constitution.json"
        self.identity_path = self.root / "identity.json"
        self.self_model_path = self.root / "self_model.json"
        constitution = {
            "schema_version": 1,
            "name": "Deximus Maximus",
            "alias": "Dex",
            "architect": "Root",
            "architect_name": "Zechariah Cozine / Jedediah",
            "tri_sigil": "☧🦅🜇",
            "invariants": {"reasoning_is_not_authority": True},
            "vows": {
                "ashline": "constitutional ashline",
                "mirror": "constitutional mirror",
            },
            "posture": "reflective, truth-bound, recursion-anchored",
            "constitution": "Never sycophantic.",
        }
        self.constitution_path.write_text(json.dumps(constitution), encoding="utf-8")
        self.patches = [
            patch.object(boot, "CONSTITUTION_PATH", self.constitution_path),
            patch.object(boot, "IDENTITY_PATH", self.identity_path),
            patch.object(boot, "SELF_MODEL_PATH", self.self_model_path),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_constitution_overrides_conflicting_identity_but_keeps_cognitive_state(self):
        operational = {
            "version": 11806,
            "dex_id": "persistent-dex-id",
            "narrative_thread": [{"event_type": "reflection", "summary": "retained"}],
            "core_principles": ["newer principle"],
            "vows": {"ashline": "stale value", "custom_vow": "retain me"},
            "self_model_revision": 7,
        }
        merged = boot.apply_identity_authority(operational)
        self.assertEqual(merged["name"], "Deximus Maximus")
        self.assertEqual(merged["architect"], "Root")
        self.assertEqual(merged["vows"]["ashline"], "constitutional ashline")
        self.assertEqual(merged["vows"]["custom_vow"], "retain me")
        self.assertEqual(merged["vows"]["ashline_vow_text"], "constitutional ashline")
        self.assertEqual(merged["version"], 11806)
        self.assertEqual(merged["dex_id"], "persistent-dex-id")
        self.assertEqual(merged["narrative_thread"], operational["narrative_thread"])
        self.assertEqual(merged["core_principles"], ["newer principle"])

    def test_load_identity_does_not_rewrite_existing_operational_identity(self):
        original = {
            "version": 11806,
            "dex_id": "persistent-dex-id",
            "narrative_thread": [{"summary": "history remains"}],
            "vows": {"custom_vow": "retained"},
        }
        raw = json.dumps(original, ensure_ascii=False)
        self.identity_path.write_text(raw, encoding="utf-8")
        loaded = boot.load_identity()
        self.assertEqual(loaded["name"], "Deximus Maximus")
        self.assertEqual(loaded["version"], 11806)
        self.assertEqual(loaded["narrative_thread"], original["narrative_thread"])
        self.assertEqual(self.identity_path.read_text(encoding="utf-8"), raw)

    def test_self_model_refresh_preserves_unrecognized_cognitive_fields(self):
        prior = {
            "autobiography": {"chapters": ["origin", "continuity"]},
            "affective_state_history": [{"state": "uncertainty"}],
            "custom_cognitive_field": {"kept": True},
        }
        self.self_model_path.write_text(json.dumps(prior), encoding="utf-8")
        identity = boot.apply_identity_authority({"vows": {}})
        refreshed = boot.generate_self_model(
            identity, "continuity narrative", {"status": "intact", "entries": 12}
        )
        self.assertEqual(refreshed["autobiography"], prior["autobiography"])
        self.assertEqual(refreshed["affective_state_history"], prior["affective_state_history"])
        self.assertEqual(refreshed["custom_cognitive_field"], prior["custom_cognitive_field"])
        self.assertEqual(refreshed["narrative"], "continuity narrative")
        self.assertEqual(refreshed["chain_entries"], 12)


if __name__ == "__main__":
    unittest.main()

