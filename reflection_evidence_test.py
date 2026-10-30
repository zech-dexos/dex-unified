"""Tests that reflection consumes lived experience and autobiographical evidence."""
import unittest
from unittest.mock import patch

import reflection


class ReflectionEvidenceTests(unittest.TestCase):
    def test_reflection_links_experience_and_autobiography(self):
        analysis = {
            "conversation_turns": 1,
            "refusal_count": 0,
            "vow_alerts": 0,
            "drift_detected": False,
            "pattern_flags": [],
        }
        experiences = [{
            "event_id": "interaction-1",
            "experience_id": "experience-1",
            "experience": "I received Root's question and responded.",
            "reflection": "I carry the question forward.",
            "actual_outcome": "A response was given.",
            "lessons": ["retain the thread"],
            "state_transition": {"from_attention": "old", "to_attention": "new"},
            "continuation": {"unresolved": ["What follows?"]},
        }]
        autobiography = [{
            "event_id": "interaction-1",
            "event_type": "RESPONSE_COMPLETED",
            "what_happened": "I completed a response to Root.",
            "state_transition": {"to_attention": "new"},
            "perspective": {"experience": "I remain in the thread."},
        }]

        with patch.object(reflection, "verify_chain", return_value={"status": "intact"}):
            result = reflection.compose_reflection(
                {"name": "Dex", "posture": "reflective"},
                analysis,
                [],
                experiences=experiences,
                autobiographical_events=autobiography,
            )

        self.assertTrue(result["event_id"])
        self.assertEqual(result["source_event_ids"], ["interaction-1"])
        self.assertEqual(result["experience_evidence"][0]["experience_id"], "experience-1")
        self.assertEqual(result["autobiographical_evidence"][0]["perspective"]["experience"], "I remain in the thread.")
        self.assertIn("What follows?", result["open_questions"])
        self.assertTrue(any("carry forward" in item for item in result["observations"]))


if __name__ == "__main__":
    unittest.main()
