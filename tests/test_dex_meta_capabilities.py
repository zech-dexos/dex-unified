import unittest
from datetime import datetime, timezone

from dex_meta_capabilities import audit_cognition, build_investigation_plan


class CognitiveAuditTests(unittest.TestCase):
    def test_detects_goal_divergence_and_repeated_thoughts(self):
        state = {
            "active_goals_state": [],
            "persistent_thoughts": [
                {"content": "Investigate SparkReach report"},
                {"content": "Investigate SparkReach report"},
                {"content": "Investigate SparkReach report"},
            ],
            "active_mental_workspace_state": {"concept_identifier": "SparkReach report"},
            "last_ambient_pulse": "2026-10-01T00:00:00Z",
        }
        participant = {"current_goals": ["Maintain continuity"]}
        result = audit_cognition(
            state=state, participant=participant, loops=[],
            experiences=[{"experience": "[all models failed]"}],
            now=datetime(2026, 10, 12, tzinfo=timezone.utc),
        )
        ids = {item["id"] for item in result["findings"]}
        self.assertIn("goal_source_divergence", ids)
        self.assertIn("thought_repetition", ids)
        self.assertIn("workspace_fixation", ids)
        self.assertIn("ambient_pulse_stale", ids)
        self.assertIn("recorded_inference_failures", ids)
        self.assertIn("no_open_loops", ids)
        self.assertTrue(result["read_only"])

    def test_clean_snapshot_has_no_findings(self):
        result = audit_cognition(
            state={"active_goals_state": ["one"], "persistent_thoughts": [],
                   "active_mental_workspace_state": {}, "last_ambient_pulse": "2026-10-12T00:00:00Z"},
            participant={}, loops=[{"id": "loop"}], experiences=[],
            now=datetime(2026, 10, 12, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result["status"], "clear")
        self.assertEqual(result["finding_count"], 0)

    def test_investigation_plan_requires_question_and_does_not_claim_execution(self):
        self.assertIn("error", build_investigation_plan(""))
        plan = build_investigation_plan("Why did inference fail?")
        self.assertEqual(plan["status"], "planned")
        self.assertTrue(plan["evidence_assessment"]["missing_primary_evidence"])
        self.assertEqual(len(plan["steps"]), 6)


if __name__ == "__main__":
    unittest.main()
