"""Tests for attention-to-workspace cognitive layer wiring."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import dex_attention
import dex_workspace
import amw
from self_state import load_self_state, update_self_state
import participant


class WorkspaceStateTests(unittest.TestCase):
    def test_new_workspace_clears_stale_attention_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            update_self_state({
                "active_mental_workspace_state": {
                    "is_active": True,
                    "concept_identifier": "old focus",
                    "attention_salience": 0.95,
                    "source_event_id": "old-event",
                    "source_interaction_event_id": "old-interaction",
                    "source_event_type": "PARTICIPANT_EVENT",
                }
            }, path=path)

            amw.activate_thought("new focus", "new focus description", path=path)
            workspace = load_self_state(path)["active_mental_workspace_state"]

        self.assertEqual(workspace["concept_identifier"], "new focus")
        self.assertEqual(workspace["attention_salience"], 0.0)
        self.assertIsNone(workspace["source_event_id"])
        self.assertIsNone(workspace["source_interaction_event_id"])
        self.assertIsNone(workspace["source_event_type"])


class ParticipantPersistenceTests(unittest.TestCase):
    def test_stale_snapshots_merge_non_overlapping_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "participant_state.json"
            with patch.object(participant, "PARTICIPANT_PATH", path):
                participant.ParticipantSnapshot().save()
                attention_writer = participant.ParticipantSnapshot.load()
                experience_writer = participant.ParticipantSnapshot.load()

                attention_writer.current_attention = "identity continuity"
                attention_writer.save()

                experience_writer.experiential_continuity = {
                    "last_experience_id": "experience-1"
                }
                experience_writer.save()

                final = participant.ParticipantSnapshot.load()
                self.assertEqual(final.current_attention, "identity continuity")
                self.assertEqual(
                    final.experiential_continuity["last_experience_id"],
                    "experience-1",
                )


class AttentionLayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_participant_event_updates_attention_and_publishes_transition(self):
        snapshot = Mock()
        snapshot.current_attention = ""
        with patch.object(dex_attention, "load_self_state", return_value={}), \
             patch.object(dex_attention, "update_self_state") as update_state, \
             patch("participant.ParticipantSnapshot.load", return_value=snapshot), \
             patch.object(dex_attention.bus, "publish", new_callable=AsyncMock) as publish:
            publish.return_value = [{
                "subscriber": "activate_workspace",
                "status": "completed",
                "result": {"event_dispatch_complete": True},
            }]
            result = await dex_attention.evaluate_salience({
                "event_type": "PARTICIPANT_EVENT",
                "event_id": "interaction-1",
                "message": "Root, this is important: preserve Dex's identity and continuity.",
            })

        self.assertEqual(result["status"], "updated")
        self.assertTrue(result["event_dispatch_complete"])
        self.assertTrue(result["event_id"])
        self.assertEqual(result["source_event_id"], "interaction-1")
        self.assertIn("identity", snapshot.current_attention.lower())
        snapshot.save.assert_called_once()
        update_state.assert_called_once()
        publish.assert_awaited_once()
        self.assertEqual(publish.await_args.args[0], "ATTENTION_CHANGED")
        self.assertEqual(publish.await_args.args[1]["event_id"], result["event_id"])
        self.assertEqual(publish.await_args.args[1]["source_event_id"], "interaction-1")

    async def test_workspace_activates_only_for_meaningful_attention(self):
        with patch.object(dex_workspace, "load_self_state", return_value={
            "active_mental_workspace_state": {"is_active": False}
        }), patch.object(dex_workspace, "activate_thought") as activate, \
             patch.object(dex_workspace, "update_self_state") as update_state, \
             patch.object(dex_workspace.bus, "publish", new_callable=AsyncMock) as publish:
            publish.return_value = [
                {"subscriber": "process_continuity_event", "status": "completed"},
                {"subscriber": "process_autobiographical_event", "status": "completed"},
            ]
            result = await dex_workspace.activate_workspace({
                "event_type": "ATTENTION_CHANGED",
                "event_id": "interaction-2",
                "focus": "continue identity reconstruction",
                "salience": 0.9,
                "source_event_type": "PARTICIPANT_EVENT",
            })

        self.assertEqual(result["status"], "activated")
        self.assertTrue(result["event_dispatch_complete"])
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
