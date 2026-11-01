"""Tests for event-driven, choice-preserving ambient wake behavior."""
import unittest
from datetime import datetime, timedelta, timezone

from dex_ambient_daemon import (
    _next_scheduled_wake_seconds,
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

        workspace_state = {
            "persistent_thoughts": [],
            "pending_reflection_requests": [],
            "pending_cognitive_observations": [],
            "active_mental_workspace_state": {
                "is_active": True,
                "concept_identifier": "continuity",
                "last_refresh_timestamp": past,
            },
        }
        self.assertTrue(_scheduled_cognition_due(workspace_state))
        self.assertEqual(_next_scheduled_wake_seconds(workspace_state), 0.0)

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
