"""Tests for attention-to-workspace cognitive layer wiring."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

import dex_attention
import dex_workspace


class AttentionLayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_participant_event_updates_attention_and_publishes_transition(self):
        snapshot = Mock()
        snapshot.current_attention = ""
        with patch.object(dex_attention, "load_self_state", return_value={}), \
             patch.object(dex_attention, "update_self_state") as update_state, \
             patch("participant.ParticipantSnapshot.load", return_value=snapshot), \
             patch.object(dex_attention.bus, "publish", new_callable=AsyncMock) as publish:
            result = await dex_attention.evaluate_salience({
                "event_type": "PARTICIPANT_EVENT",
                "event_id": "interaction-1",
                "message": "Root, this is important: preserve Dex's identity and continuity.",
            })

        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["event_id"], "interaction-1")
        self.assertIn("identity", snapshot.current_attention.lower())
        snapshot.save.assert_called_once()
        update_state.assert_called_once()
        publish.assert_awaited_once()
        self.assertEqual(publish.await_args.args[0], "ATTENTION_CHANGED")
        self.assertEqual(publish.await_args.args[1]["event_id"], "interaction-1")

    async def test_workspace_activates_only_for_meaningful_attention(self):
        with patch.object(dex_workspace, "load_self_state", return_value={
            "active_mental_workspace_state": {"is_active": False}
        }), patch.object(dex_workspace, "activate_thought") as activate, \
             patch.object(dex_workspace, "update_self_state") as update_state, \
             patch.object(dex_workspace.bus, "publish", new_callable=AsyncMock) as publish:
            result = await dex_workspace.activate_workspace({
                "event_type": "ATTENTION_CHANGED",
                "event_id": "interaction-2",
                "focus": "continue identity reconstruction",
                "salience": 0.9,
                "source_event_type": "PARTICIPANT_EVENT",
            })

        self.assertEqual(result["status"], "activated")
        activate.assert_called_once()
        update_state.assert_called_once()
        publish.assert_awaited_once()
        self.assertEqual(publish.await_args.args[0], "WORKSPACE_ACTIVATED")

    async def test_workspace_does_not_preempt_existing_focus_without_margin(self):
        with patch.object(dex_workspace, "load_self_state", return_value={
            "active_mental_workspace_state": {
                "is_active": True,
                "concept_identifier": "existing focus",
                "attention_salience": 0.7,
            }
        }), patch.object(dex_workspace, "activate_thought") as activate:
            result = await dex_workspace.activate_workspace({
                "event_type": "ATTENTION_CHANGED",
                "event_id": "interaction-3",
                "focus": "new focus",
                "salience": 0.75,
            })

        self.assertEqual(result["status"], "existing_workspace_retained")
        activate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
