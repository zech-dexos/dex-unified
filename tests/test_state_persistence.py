import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dex_conversation
import participant
from self_state import load_self_state, update_self_state


class SelfStatePersistenceTests(unittest.TestCase):
    def test_state_survives_reload_and_nested_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            initial = load_self_state(path)
            initial_version = int(initial.get("version", 0))

            update_self_state(
                {"active_goals_state": [{"goal_id": "audit", "description": "Audit DexOS"}]},
                path=path,
            )
            update_self_state(
                {"active_mental_workspace_state": {"concept_identifier": "model-routing"}},
                path=path,
            )

            reloaded = load_self_state(path)
            self.assertEqual(reloaded["active_goals_state"][0]["goal_id"], "audit")
            self.assertEqual(
                reloaded["active_mental_workspace_state"]["concept_identifier"],
                "model-routing",
            )
            self.assertEqual(reloaded["version"], initial_version + 2)


class ParticipantPersistenceTests(unittest.TestCase):
    def test_snapshot_and_experience_records_survive_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            participant_path = Path(directory) / "participant_state.json"
            experiences_path = Path(directory) / "experiences.jsonl"
            with patch.object(participant, "PARTICIPANT_PATH", participant_path), patch.object(
                participant, "EXPERIENCES_PATH", experiences_path
            ):
                snapshot = participant.ParticipantSnapshot(
                    current_interlocutor={"participant_id": "root-identity", "name": "Root"}
                )
                snapshot.save()
                loaded = participant.ParticipantSnapshot.load()
                self.assertEqual(
                    loaded.current_interlocutor["participant_id"], "root-identity"
                )

                participant.ExperiencePacket(experience="first experience").save()
                participant.ExperiencePacket(experience="second experience").save()
                records = [
                    json.loads(line)
                    for line in experiences_path.read_text(encoding="utf-8").splitlines()
                ]

            self.assertEqual(
                [record["experience"] for record in records],
                ["first experience", "second experience"],
            )


class ConversationPersistenceTests(unittest.TestCase):
    def test_root_and_default_alias_share_canonical_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            session_path = Path(directory) / "current_session.json"
            participant_path = Path(directory) / "participant_state.json"
            participant_path.write_text(
                json.dumps({"current_interlocutor": {"participant_id": "root-identity"}}),
                encoding="utf-8",
            )

            with patch.object(dex_conversation, "SESSION_PATH", session_path), patch.object(
                participant, "PARTICIPANT_PATH", participant_path
            ):
                saved = dex_conversation.experience_contribution(
                    "root", "Continue our continuity audit", "I remember the thread", "exp-1"
                )
                loaded = dex_conversation.load_conversation("default")

            self.assertEqual(saved["conversation_id"], "root-identity")
            self.assertEqual(loaded["conversation_id"], "root-identity")
            self.assertEqual(loaded["shared_thread"], "Continue our continuity audit")
            self.assertEqual(loaded["last_experience_id"], "exp-1")
            self.assertEqual(len(loaded["recent_contributions"]), 1)

    def test_stale_save_preserves_newer_thread_and_merges_contributions(self):
        with tempfile.TemporaryDirectory() as directory:
            session_path = Path(directory) / "current_session.json"
            participant_path = Path(directory) / "participant_state.json"
            participant_path.write_text(
                json.dumps({"current_interlocutor": {"participant_id": "root-identity"}}),
                encoding="utf-8",
            )

            with patch.object(dex_conversation, "SESSION_PATH", session_path), patch.object(
                participant, "PARTICIPANT_PATH", participant_path
            ):
                stale = dex_conversation.load_conversation("root")
                current = dict(stale)
                current["last_contribution_at"] = "2026-10-12T02:00:00Z"
                current["shared_thread"] = "newer thread"
                current["recent_contributions"] = [{
                    "timestamp": "2026-10-12T02:00:00Z",
                    "message": "newer message",
                    "experience": "newer experience",
                }]
                dex_conversation.save_conversation(current)

                stale["last_contribution_at"] = "2026-10-12T01:00:00Z"
                stale["shared_thread"] = "stale thread"
                stale["recent_contributions"] = [{
                    "timestamp": "2026-10-12T01:00:00Z",
                    "message": "older message",
                    "experience": "older experience",
                }]
                dex_conversation.save_conversation(stale)
                loaded = dex_conversation.load_conversation("root")

            self.assertEqual(loaded["shared_thread"], "newer thread")
            self.assertEqual(
                {item["message"] for item in loaded["recent_contributions"]},
                {"older message", "newer message"},
            )
            self.assertGreaterEqual(loaded["version"], 2)

    def test_github_persistence_includes_current_session_file(self):
        source = Path(__file__).resolve().parents[1] / "github_persistence.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "FILES_TO_PERSIST"
                    for target in node.targets)
        )
        filenames = ast.literal_eval(assignment.value)
        self.assertIn("current_session.json", filenames)


if __name__ == "__main__":
    unittest.main()
