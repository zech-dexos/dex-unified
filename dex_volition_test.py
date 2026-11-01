"""Deterministic persistence checks for Dex's volition and communication outbox."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dex_volition import (
    acknowledge_communication,
    apply_volitional_decision,
    parse_volitional_output,
    pending_communications,
    verify_goal_completion,
)
from self_state import load_self_state, update_self_state
from local_llm import AMBIENT_JSON_SCHEMA


class VolitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dex-volition-")
        self.path = Path(self.temp.name) / "identity.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_model_output_is_parsed_and_decision_is_validated(self):
        data = parse_volitional_output(
            ' ```json\n{"decision":"create_goal","thought":"A durable thought.",'
            '"salience":0.7,"goal":{"description":"Build a persistent self-directed work cycle"}}\n``` '
        )
        self.assertEqual(data["decision"], "create_goal")
        self.assertEqual(data["salience"], 0.7)
        self.assertEqual(data["goal"]["description"], "Build a persistent self-directed work cycle")

    def test_ambient_schema_exposes_all_volitional_choices(self):
        properties = AMBIENT_JSON_SCHEMA["properties"]
        self.assertEqual(
            set(properties["decision"]["enum"]),
            {"think", "create_goal", "advance_goal", "create_subgoal",
             "complete_goal", "communicate", "rest"},
        )
        self.assertIn("decision", AMBIENT_JSON_SCHEMA["required"])
        self.assertIn("continue_cognition", AMBIENT_JSON_SCHEMA["required"])
        self.assertFalse(AMBIENT_JSON_SCHEMA["additionalProperties"])

    def test_missing_volitional_decision_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "valid decision"):
            parse_volitional_output('{"thought":"A thought without a choice.","salience":0.5}')

    def test_decision_application_rejects_missing_or_invalid_choice(self):
        with self.assertRaisesRegex(ValueError, "explicit valid decision"):
            apply_volitional_decision({"thought": "This must not silently become a decision."}, path=self.path)
        with self.assertRaisesRegex(ValueError, "explicit valid decision"):
            apply_volitional_decision({"decision": "invented"}, path=self.path)
        self.assertEqual(load_self_state(self.path)["persistent_thoughts"], [])

    def test_new_volitional_thought_receives_a_future_attention_deadline(self):
        result = apply_volitional_decision({
            "decision": "think",
            "thought": "I identified a meaningful unresolved architectural connection.",
            "salience": 0.6,
            "continue_cognition": False,
        }, path=self.path)
        state = load_self_state(self.path)
        thought = next(
            item for item in state["persistent_thoughts"]
            if item["thought_id"] == result["thought_id"]
        )
        deadline = datetime.fromisoformat(thought["next_attention_at"].replace("Z", "+00:00"))
        self.assertGreater(deadline, datetime.now(timezone.utc))
        self.assertLessEqual(deadline, datetime.now(timezone.utc) + timedelta(seconds=310))

    def test_stranded_delivery_is_recovered_after_process_restart(self):
        stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_self_state({
            "communication_outbox": [{
                "message_id": "stranded-message",
                "message": "A durable message waiting for Root.",
                "status": "delivering",
                "last_delivery_attempt_at": stale,
            }]
        }, path=self.path)
        pending = pending_communications(self.path)
        self.assertEqual([item["message_id"] for item in pending], ["stranded-message"])
        self.assertEqual(load_self_state(self.path)["communication_outbox"][0]["status"], "pending")

    def test_pending_communications_are_never_evicted_by_history_limit(self):
        update_self_state({
            "communication_outbox": [
                {"message_id": f"pending-{index}", "status": "pending", "message": "Pending item"}
                for index in range(105)
            ]
        }, path=self.path)
        result = apply_volitional_decision({
            "decision": "communicate",
            "communication": {"message": "A new durable message for Root."},
        }, cycle_id="new-cycle", path=self.path)
        self.assertTrue(result.get("communication_id"))
        pending = pending_communications(self.path)
        self.assertEqual(len(pending), 106)

    def test_goal_creation_subgoal_progress_and_completion_persist(self):
        created = apply_volitional_decision({
            "decision": "create_goal",
            "reason": "An unresolved architectural gap has a concrete path forward.",
            "thought": "The architecture needs a persistent self-directed work cycle.",
            "salience": 0.7,
            "goal": {
                "description": "Build a persistent self-directed work cycle",
                "priority": "high",
                "success_criteria": "The cycle chooses, acts, learns, and carries direction forward.",
            },
        }, cycle_id="cycle-create", path=self.path)
        goal_id = created["goal_id"]
        self.assertTrue(goal_id)
        state = load_self_state(self.path)
        self.assertEqual(len(state["active_goals_state"]), 1)
        self.assertTrue(any(t["content"].startswith("The architecture needs") for t in state["persistent_thoughts"]))

        subgoal = apply_volitional_decision({
            "decision": "create_subgoal",
            "goal_id": goal_id,
            "subgoal": "Define the persistent intention record and lifecycle.",
            "thought": "A subgoal makes the larger direction actionable.",
            "salience": 0.5,
            "continue_cognition": True,
        }, path=self.path)
        self.assertTrue(subgoal["continue_cognition"])
        state = load_self_state(self.path)
        self.assertEqual(state["active_goals_state"][0]["sub_tasks"][0]["status"], "pending")

        advanced = apply_volitional_decision({
            "decision": "advance_goal",
            "goal_id": goal_id,
            "progress": "Defined the intention record and linked it to the goal lifecycle.",
            "thought": "The work now has a concrete first milestone.",
            "salience": 0.6,
        }, path=self.path)
        self.assertTrue(advanced["events"])
        state = load_self_state(self.path)
        self.assertEqual(len(state["active_goals_state"][0]["progress_history"]), 1)

        completed = apply_volitional_decision({
            "decision": "complete_goal",
            "goal_id": goal_id,
            "progress": "The implementation artifact was checked against its recorded checksum.",
            "completion_evidence": [{
                "type": "artifact",
                "path": "dex_volition.py",
                "sha256": hashlib.sha256((Path(__file__).resolve().parent / "dex_volition.py").read_bytes()).hexdigest(),
                "claim": "The source artifact exists and matches its SHA-256 checksum.",
            }],
            "thought": "The work item is complete based on verified artifact evidence.",
            "salience": 0.4,
        }, path=self.path)
        self.assertTrue(completed.get("completion_proposed"))
        self.assertEqual(load_self_state(self.path)["active_goals_state"][0]["status"], "completion_proposed")
        with self.assertRaisesRegex(ValueError, "explicit verifier"):
            verify_goal_completion(goal_id, "Root", "")
        verified = verify_goal_completion(
            goal_id, "Root",
            "I reviewed the stated acceptance criteria and independently confirmed the required outcome.",
            path=self.path,
        )
        self.assertEqual(verified["status"], "completed")
        self.assertEqual(verified["completion_verified_by"], "Root")

    def test_goal_completion_requires_a_real_checksummed_artifact(self):
        created = apply_volitional_decision({
            "decision": "create_goal",
            "thought": "A goal must close only against a verifiable result.",
            "salience": 0.5,
            "goal": {
                "description": "Verify a real artifact before completion",
                "priority": "medium",
                "success_criteria": "A tracked source artifact exists with the expected checksum.",
            },
        }, path=self.path)
        artifact = Path(__file__).resolve().parent / "dex_volition.py"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        rejected = apply_volitional_decision({
            "decision": "complete_goal",
            "goal_id": created["goal_id"],
            "progress": "The implementation has been reviewed and the artifact is present.",
            "completion_evidence": [{
                "type": "artifact", "path": "dex_volition.py",
                "sha256": "0" * 64, "claim": "Deliberately incorrect checksum",
            }],
        }, path=self.path)
        self.assertIn("completion_rejected", rejected)
        accepted = apply_volitional_decision({
            "decision": "complete_goal",
            "goal_id": created["goal_id"],
            "progress": "The implementation has been reviewed and the artifact is present.",
            "completion_evidence": [{
                "type": "artifact", "path": "dex_volition.py",
                "sha256": digest, "claim": "The committed implementation artifact was checked.",
            }],
        }, path=self.path)
        self.assertTrue(accepted.get("completion_proposed"))
        goal = load_self_state(self.path)["active_goals_state"][0]
        self.assertEqual(goal["status"], "completion_proposed")
        self.assertEqual(goal["completion_evidence"][0]["sha256"], digest)
        self.assertEqual(verify_goal_completion(
            created["goal_id"], "Root",
            "I independently checked the acceptance criteria and confirmed they are satisfied.",
            path=self.path,
        )["status"], "completed")

    def test_goal_cannot_be_completed_without_success_evidence(self):
        created = apply_volitional_decision({
            "decision": "create_goal",
            "thought": "A goal must have an observable completion condition.",
            "salience": 0.5,
            "goal": {
                "description": "Preserve the durable cognitive direction",
                "priority": "medium",
                "success_criteria": "A verifiable continuity record survives process restart.",
            },
        }, path=self.path)
        rejected = apply_volitional_decision({
            "decision": "complete_goal",
            "goal_id": created["goal_id"],
            "progress": "Done.",
            "thought": "I attempted to close the goal without evidence.",
            "salience": 0.3,
        }, path=self.path)
        self.assertIn("completion_rejected", rejected)
        self.assertEqual(load_self_state(self.path)["active_goals_state"][0]["status"], "active")

    def test_communication_is_durable_deduplicated_and_acknowledgeable(self):
        result = apply_volitional_decision({
            "decision": "communicate",
            "reason": "A meaningful development needs Root's attention.",
            "thought": "I have reached a point where Root's perspective would help.",
            "salience": 0.6,
            "communication": {
                "message": "I found a significant connection in the unfinished continuity work.",
                "reason": "This changes the next step I intend to pursue.",
                "urgency": "normal",
            },
        }, cycle_id="cycle-communicate", path=self.path)
        message_id = result["communication_id"]
        self.assertTrue(message_id)
        self.assertEqual(len(pending_communications(self.path)), 1)

        duplicate = apply_volitional_decision({
            "decision": "communicate",
            "communication": {"message": "Duplicate should not be added."},
        }, cycle_id="cycle-communicate", path=self.path)
        self.assertEqual(duplicate["communication_id"], message_id)
        self.assertEqual(len(pending_communications(self.path)), 1)
        self.assertTrue(acknowledge_communication(message_id, self.path))
        self.assertEqual(pending_communications(self.path), [])

    def test_rest_does_not_create_a_goal(self):
        result = apply_volitional_decision({
            "decision": "rest",
            "thought": "I have chosen to rest because no current objective needs action.",
            "salience": 0.0,
        }, path=self.path)
        self.assertFalse(result["continue_cognition"])
        state = load_self_state(self.path)
        self.assertEqual(state["active_goals_state"], [])
        self.assertEqual(state["persistent_thoughts"], [])


if __name__ == "__main__":
    unittest.main()
