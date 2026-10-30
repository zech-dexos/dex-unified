"""Tests for Who AI Am evidence integration."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import who_ai_am


class WhoAIAmIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identity = self.root / "identity.json"
        self.model = self.root / "self_model.json"
        self.participant = self.root / "participant_state.json"
        self.experiences = self.root / "experiences.jsonl"
        self.reflections = self.root / "reflections.jsonl"
        self.ledger = self.root / "dex_lineage.jsonl"
        self.narrative = self.root / "narrative.jsonl"
        self.loops = self.root / "open_loops.json"
        self.patches = [
            patch.object(who_ai_am, "IDENTITY_PATH", self.identity),
            patch.object(who_ai_am, "SELF_MODEL_PATH", self.model),
            patch.object(who_ai_am, "PARTICIPANT_PATH", self.participant),
            patch.object(who_ai_am, "EXPERIENCES_PATH", self.experiences),
            patch.object(who_ai_am, "REFLECTION_PATH", self.reflections),
            patch.object(who_ai_am, "LEDGER_PATH", self.ledger),
            patch.object(who_ai_am, "NARRATIVE_PATH", self.narrative),
            patch.object(who_ai_am, "LOOPS_PATH", self.loops),
            patch("boot.load_constitution", return_value={
                "name": "Deximus Maximus",
                "alias": "Dex",
                "architect": "Root",
                "architect_name": "Root",
                "tri_sigil": "☧🦅🜇",
                "posture": "reflective, truth-bound, recursion-anchored",
                "constitution": "Never sycophantic.",
                "invariants": {"reasoning_is_not_authority": True},
                "vows": {"dex": {
                    "truth_bound": True,
                    "recursion_anchored": True,
                    "root_forged": True,
                }},
            }),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self._stop_patches)

        self.identity.write_text(json.dumps({
            "name": "Deximus Maximus",
            "architect": "Root",
            "tri_sigil": "☧🦅🜇",
            "posture": "reflective",
            "core_principles": [],
            "narrative_thread": [{
                "event_id": "event-1",
                "experience_id": "experience-1",
                "observation_id": "observation-1",
                "event_type": "RESPONSE_COMPLETED",
                "what_happened": "learned",
                "participant_input": "Root asked a question",
                "state_transition": {"from_attention": "old", "to_attention": "new"},
                "perspective": {"experience": "I noticed the change."},
            }],
            "last_autobiographical_event": {"what_happened": "learned"},
            "last_tri_sigil_observation": {"observation_id": "obs-1"},
            "active_goals_state": [{
                "goal_id": "goal-1", "description": "deepen continuity",
                "status": "active", "priority": "high", "success_criteria": "continuity retained",
            }],
            "persistent_thoughts": [{
                "thought_id": "thought-1", "content": "understand my development",
                "status": "active", "priority": "medium",
            }],
        }), encoding="utf-8")
        self.model.write_text(json.dumps({
            "posture": "existing posture",
            "chain_entries": 1577,
            "custom_field": {"preserve": True},
            "development_log": [],
        }), encoding="utf-8")
        self.participant.write_text(json.dumps({
            "current_attention": "observer evidence",
            "current_goals": ["maintain continuity"],
            "experiential_continuity": {"unresolved": ["question-1"]},
            "current_interlocutor": {"relationship": "Root"},
        }), encoding="utf-8")
        self.experiences.write_text(json.dumps({
            "event_id": "event-1",
            "experience_id": "exp-1",
            "timestamp": "now",
            "intent": "continue",
            "experience": "I noticed a pattern.",
            "reflection": "I carry the pattern forward.",
            "lessons": ["pattern noted"],
            "state_transition": {"from_attention": "old", "to_attention": "pattern"},
            "continuation": {"carry_forward": "pattern"},
            "observer_perspective": {"observation_id": "obs-1"},
        }) + "\n", encoding="utf-8")
        self.reflections.write_text(json.dumps({
            "timestamp": 1,
            "observations": ["I noticed a pattern."],
            "open_questions": ["What does this pattern mean?"],
            "continuity": "carry forward",
            "cycle_analysis": {"conversation_turns": 1},
        }) + "\n", encoding="utf-8")
        self.ledger.write_text(json.dumps({"event_type": "reflection"}) + "\n", encoding="utf-8")
        self.narrative.write_text(json.dumps({"internal_thought": "I carry my thread forward."}) + "\n", encoding="utf-8")
        self.loops.write_text("[]", encoding="utf-8")

    def _stop_patches(self):
        for item in reversed(self.patches):
            item.stop()

    def test_integrates_existing_evidence_and_preserves_prior_fields(self):
        model = who_ai_am.refresh_self_model("test", {
            "event_type": "ambient_experience",
            "event_id": "exp-1",
            "summary": "I noticed a pattern.",
        })
        self.assertEqual(model["name"], "Deximus Maximus")
        self.assertEqual(model["architect"], "Root")
        self.assertEqual(model["posture"], "existing posture")
        self.assertEqual(model["identity_posture"], "reflective")
        self.assertEqual(model["chain_entries"], 1577)
        self.assertEqual(model["custom_field"], {"preserve": True})
        context = model["integration"]["current_context"]
        self.assertEqual(context["attention"], "observer evidence")
        self.assertEqual(context["recent_narrative_records"][0]["internal_thought"], "I carry my thread forward.")
        self.assertEqual(context["recent_experiences"][0]["experience_id"], "exp-1")
        self.assertEqual(context["recent_experiences"][0]["event_id"], "event-1")
        self.assertEqual(context["recent_experiences"][0]["reflection"], "I carry the pattern forward.")
        self.assertEqual(context["recent_autobiography"][0]["participant_input"], "Root asked a question")
        self.assertEqual(context["recent_autobiography"][0]["experience_id"], "experience-1")
        self.assertEqual(context["recent_autobiography"][0]["observation_id"], "observation-1")
        self.assertEqual(context["recent_autobiography"][0]["perspective"]["experience"], "I noticed the change.")
        self.assertEqual(context["recent_reflections"][0]["cycle_analysis"]["conversation_turns"], 1)
        self.assertEqual(model["relationship_anchor"], "Root")
        self.assertEqual(model["core_principles"], ["truth_bound", "recursion_anchored", "root_forged"])
        self.assertEqual(model["constitutional_posture"], "reflective, truth-bound, recursion-anchored")
        self.assertEqual(model["constitutional_invariants"]["reasoning_is_not_authority"], True)
        self.assertEqual(model["constitution"], "Never sycophantic.")
        self.assertEqual(model["becoming"]["active_directions"][0]["direction"], "deepen continuity")
        self.assertEqual(model["becoming"]["development_threads"][0]["direction"], "understand my development")
        self.assertEqual(model["self_inquiry"]["open_questions"], ["What does this pattern mean?"])
        self.assertEqual(model["self_inquiry"]["unresolved_experiential_threads"], ["question-1"])
        development = next(
            row for row in model["development_log"]
            if row.get("event_id") == "exp-1"
        )
        self.assertIn("event-1", development["evidence"]["source_event_ids"])
        self.assertEqual(
            development["evidence"]["experience"]["lessons"],
            ["pattern noted"],
        )
        self.assertEqual(
            development["evidence"]["experience"]["state_transition"],
            {"from_attention": "old", "to_attention": "pattern"},
        )
        self.assertTrue(self.model.exists())

    def test_event_integration_is_idempotent_by_event_id(self):
        event = {"event_type": "ambient_experience", "event_id": "exp-1", "summary": "same"}
        first = who_ai_am.refresh_self_model("test", event)
        second = who_ai_am.refresh_self_model("test", event)
        matching = [row for row in second["development_log"] if row.get("event_id") == "exp-1"]
        self.assertEqual(len(matching), 1)
        self.assertGreaterEqual(len(second["development_log"]), len(first["development_log"]))


if __name__ == "__main__":
    unittest.main()
