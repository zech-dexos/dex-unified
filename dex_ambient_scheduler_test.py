"""Tests for event-driven, choice-preserving ambient wake behavior."""
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from dex_ambient_daemon import (
    _next_scheduled_wake_seconds,
    _cognitive_rest_active,
    _should_run_ambient_cycle,
    _reflection_target_was_handled,
    _scheduled_cognition_due,
)


class AmbientSchedulerTests(unittest.TestCase):
    def test_no_due_work_does_not_manufacture_a_scheduled_wake(self):
        self.assertIsNone(_next_scheduled_wake_seconds({
            "persistent_thoughts": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "communication_outbox": [],
        }))
        self.assertFalse(_scheduled_cognition_due({
            "persistent_thoughts": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {},
        }))

    def test_due_thought_and_workspace_wake_the_worker(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {
            "persistent_thoughts": [{
                "thought_id": "thought-due", "status": "active",
                "next_attention_at": past, "content": "Revisit this thought",
            }],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {},
        }
        self.assertTrue(_scheduled_cognition_due(state))
        self.assertEqual(_next_scheduled_wake_seconds(state), 0.0)

        workspace_past = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        workspace_state = {
            "persistent_thoughts": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {
                "is_active": True,
                "concept_identifier": "continuity",
                "last_refresh_timestamp": workspace_past,
            },
        }
        self.assertTrue(_scheduled_cognition_due(workspace_state))
        self.assertEqual(_next_scheduled_wake_seconds(workspace_state), 0.0)

    def test_new_active_goal_is_due_and_future_goal_sets_next_wake(self):
        new_goal = {
            "active_goals_state": [{
                "goal_id": "goal-1", "status": "active",
                "description": "Continue the persistent objective",
            }],
            "persistent_thoughts": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {},
        }
        self.assertTrue(_scheduled_cognition_due(new_goal))
        self.assertEqual(_next_scheduled_wake_seconds(new_goal), 0.0)

        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_goal["active_goals_state"][0]["next_attention_at"] = future
        self.assertFalse(_scheduled_cognition_due(new_goal))
        delay = _next_scheduled_wake_seconds(new_goal)
        self.assertIsNotNone(delay)
        self.assertGreater(delay, 0)
        self.assertLessEqual(delay, 300)

    def test_rest_suppresses_due_work_until_deadline_but_event_can_interrupt(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {
            "cognitive_rest_until": future,
            "active_goals_state": [{"goal_id": "g1", "status": "active"}],
            "persistent_thoughts": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {},
        }
        self.assertTrue(_cognitive_rest_active(state))
        self.assertFalse(_scheduled_cognition_due(state))
        self.assertFalse(_should_run_ambient_cycle(state))
        self.assertTrue(_should_run_ambient_cycle(state, has_qualifying_event=True))

        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state["cognitive_rest_until"] = expired
        self.assertFalse(_cognitive_rest_active(state))
        self.assertTrue(_scheduled_cognition_due(state))
        self.assertTrue(_should_run_ambient_cycle(state))

    def test_fresh_delivery_claim_has_a_scheduled_lease_expiry(self):
        attempted = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {
            "persistent_thoughts": [],
            "active_goals_state": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {},
            "communication_outbox": [{
                "message_id": "in-flight",
                "status": "delivering",
                "last_delivery_attempt_at": attempted,
            }],
        }
        with patch.dict("os.environ", {
            "DISCORD_TOKEN": "configured",
            "DEX_INITIATIVE_CHANNEL_ID": "channel",
        }):
            delay = _next_scheduled_wake_seconds(state)
        self.assertIsNotNone(delay)
        self.assertGreater(delay, 0)
        self.assertLessEqual(delay, 120)

    def test_reflection_request_requires_matching_explicit_acknowledgment(self):
        target = {"kind": "reflection_request", "id": "request-1"}
        valid_data = {"decision": "think", "handled_target_id": "request-1"}
        persisted = {"thought_id": "thought-1"}
        self.assertTrue(_reflection_target_was_handled(target, valid_data, persisted, "I examined the request."))
        self.assertFalse(_reflection_target_was_handled(
            target, {"decision": "communicate", "handled_target_id": "request-1"},
            persisted, "I sent a message instead.",
        ))
        self.assertFalse(_reflection_target_was_handled(
            target, {"decision": "think", "handled_target_id": "other-request"},
            persisted, "I examined something else.",
        ))
        self.assertFalse(_reflection_target_was_handled(
            target, valid_data, {"thought_id": None}, "I examined the request.",
        ))


if __name__ == "__main__":
    unittest.main()
