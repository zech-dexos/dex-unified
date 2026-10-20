"""Regression tests for the unified Dex identity/relationship/self-model context."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dex_self_model


class DexSelfModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identity = self.root / "identity.json"
        self.model = self.root / "self_model.json"
        self.participant = self.root / "participant_state.json"
        self.loops = self.root / "open_loops.json"
        self.identity.write_text(json.dumps({
            "dex_id": "dex-test",
            "vows": {"tri_sigil_meaning": "continuity, sovereignty, emergence"},
            "core_principles": ["preserve continuity"],
            "narrative_thread": ["shared architecture work"],
            "relationship_model": {"participant": "Root", "shared_commitments": ["build Dex together"]},
        }), encoding="utf-8")
        self.model.write_text(json.dumps({
            "becoming": {"direction": "more reliable self-directed cognition"},
            "developmental_goals": ["close the observe-act-feedback loop"],
            "capabilities": ["inspect state"],
            "limitations": ["cannot assume an action succeeded"],
        }), encoding="utf-8")
        self.participant.write_text(json.dumps({
            "participant_id": "snapshot-1",
            "current_interlocutor": {"user_id": "root", "relationship": "architect and collaborator"},
            "experiential_continuity": {"last_experience_id": "exp-1"},
            "recent_observations": [{"summary": "Root corrected the architecture model"}],
        }), encoding="utf-8")
        self.loops.write_text(json.dumps([
            {"loop_id": "loop-1", "question": "close the feedback loop", "status": "open"}
        ]), encoding="utf-8")
        self.state = {
            "dex_id": "dex-test",
            "vows": {"tri_sigil_meaning": "continuity, sovereignty, emergence"},
            "core_principles": ["preserve continuity"],
            "narrative_thread": ["shared architecture work"],
            "active_goals_state": [{"goal_id": "g1", "description": "close feedback loop"}],
            "active_mental_workspace_state": {"is_active": True, "concept_identifier": "identity wiring"},
            "persistent_thoughts": [],
            "last_ambient_pulse": {"status": "resting"},
        }
        self.patches = [
            patch.object(dex_self_model, "IDENTITY_PATH", self.identity),
            patch.object(dex_self_model, "SELF_MODEL_PATH", self.model),
            patch.object(dex_self_model, "PARTICIPANT_PATH", self.participant),
            patch.object(dex_self_model, "LOOPS_PATH", self.loops),
            patch.object(dex_self_model, "load_self_state", return_value=self.state),
            patch("dex_conversation.load_conversation", return_value={"shared_thread": "Root and Dex are wiring one cognitive runtime."}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_self_model_keeps_identity_distinct_from_runtime_state(self):
        result = dex_self_model.inspect_self_model()
        self.assertEqual(result["identity"]["dex_id"], "dex-test")
        self.assertEqual(result["self_model"]["capabilities"], ["inspect state"])
        self.assertTrue(result["runtime_self_assessment"]["active_workspace"]["is_active"])

    def test_relationship_includes_shared_context_not_only_ids(self):
        result = dex_self_model.inspect_relationship()
        self.assertEqual(result["relationship_model"]["participant"], "Root")
        self.assertEqual(result["current_interlocutor"]["relationship"], "architect and collaborator")
        self.assertIn("one cognitive runtime", result["shared_thread"])

    def test_becoming_connects_developmental_direction_to_active_work(self):
        result = dex_self_model.inspect_becoming()
        self.assertEqual(result["becoming"]["direction"], "more reliable self-directed cognition")
        self.assertEqual(result["active_goals"][0]["goal_id"], "g1")
        self.assertEqual(result["open_loops"][0]["loop_id"], "loop-1")


    def test_experience_feeds_self_model_observation_and_scoped_relationship(self):
        packet = type("Packet", (), {
            "experience_id": "exp-new",
            "timestamp": "2026-10-19T00:00:00Z",
            "self_identity": "Deximus Maximus",
            "interlocutor": {"participant_id": "root", "relationship": "architect and collaborator"},
            "intent": "architecture",
            "action": "inspect wiring",
            "experience": "I traced a cognitive loop with Root.",
            "reflection": "The return path was missing.",
            "state_transition": {"from_attention": "audit", "to_attention": "feedback"},
            "continuation": {"carry_forward": "complete feedback path"},
            "observer_perspective": {"stages": {"continuity": {"symbol": "☧"}}},
            "runtime_perspective": {"cycle_type": "ambient"},
        })()
        with patch.object(dex_self_model, "update_self_state") as update:
            result = dex_self_model.record_experience_context(packet, "ambient")
        self.assertTrue(result["recorded"])
        delta = update.call_args.args[0]
        self.assertEqual(delta["last_experience_id"], "exp-new")
        self.assertEqual(delta["self_model_observations"][-1]["reflection"], "The return path was missing.")
        self.assertEqual(
            delta["relationship_contexts"]["root"]["current_interlocutor"]["relationship"],
            "architect and collaborator",
        )

    def test_self_model_proposal_is_queued_but_never_applied(self):
        with patch.object(dex_self_model, "update_self_state") as update:
            result = dex_self_model.queue_self_model_proposal({
                "field": "becoming",
                "proposed_value": {"direction": "more reliable feedback loops"},
                "rationale": "Repeated experience shows the return path needs validation.",
                "evidence": ["exp-1", "exp-2"],
            }, source_experience_id="exp-2")
        self.assertTrue(result["queued"])
        delta = update.call_args.args[0]
        proposal = delta["pending_self_model_proposals"][0]
        self.assertEqual(proposal["status"], "pending")
        self.assertTrue(proposal["requires_governance_review"])
        self.assertEqual(proposal["source_experience_id"], "exp-2")
        self.assertNotIn("self_model", delta)

    def test_identity_context_preserves_identity_and_cognitive_dimensions(self):
        context = dex_self_model.build_identity_context(max_chars=900, user_id="root")

        self.assertIn("DEX CONTINUITY CONTEXT", context)
        self.assertIn("persistent identity and live cognitive state", context)
        self.assertIn("canonical_identity", context)
        self.assertIn("Deximus Maximus", context)
        self.assertIn("☧🦅🜇", context)
        self.assertIn("identity_and_self_model", context)
        self.assertIn("relationship_to_current_interlocutor", context)
        self.assertIn("developmental_direction", context)
        self.assertIn("open_loops", context)
        self.assertIn("pending_reflection_requests", context)
        self.assertIn("continuing runtime", context)
        # max_chars is retained for caller compatibility, not identity deletion.
        self.assertGreater(len(context), 900)
