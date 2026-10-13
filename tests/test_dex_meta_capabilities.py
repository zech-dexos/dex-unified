import unittest
from datetime import datetime, timezone

from dex_meta_capabilities import audit_cognition, build_investigation_plan, evaluate_investigation


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


    def test_evaluator_reports_mixed_evidence_without_claiming_verification(self):
        result = evaluate_investigation("Is the pulse running?", [
            {"source": "scheduler log", "observation": "job succeeded", "relation": "supports"},
            {"source": "runtime state", "observation": "pulse timestamp is stale", "relation": "contradicts"},
            {"source": "bad item", "observation": "", "relation": "supports"},
        ])
        self.assertEqual(result["verdict"], "mixed")
        self.assertEqual(result["counts"]["supports"], 1)
        self.assertEqual(result["counts"]["contradicts"], 1)
        self.assertEqual(result["invalid_evidence_count"], 1)
        self.assertTrue(result["read_only"])
        self.assertIn("not independently verified", " ".join(result["limitations"]))

    def test_evaluator_requires_directional_evidence(self):
        result = evaluate_investigation("Did the fix work?", [
            {"source": "test output", "observation": "test ran", "relation": "neutral"},
        ])
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(evaluate_investigation("")["error"], "question is required")


if __name__ == "__main__":
    unittest.main()
