"""Deterministic persistence checks for Dex's volition and communication outbox."""
import json
import tempfile
import unittest
from pathlib import Path

from dex_volition import (
    acknowledge_communication,
    apply_volitional_decision,
    parse_volitional_output,
    pending_communications,
)
from self_state import load_self_state


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
            "progress": "Acceptance evidence confirms the defined success criteria.",
            "thought": "The work item is complete based on recorded evidence.",
            "salience": 0.4,
        }, path=self.path)
        self.assertTrue(completed["events"])
        self.assertEqual(load_self_state(self.path)["active_goals_state"][0]["status"], "completed")

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
            "thought": "",
            "salience": 0.0,
        }, path=self.path)
        self.assertFalse(result["continue_cognition"])
        self.assertEqual(load_self_state(self.path)["active_goals_state"], [])


if __name__ == "__main__":
    unittest.main()
