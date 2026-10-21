"""Regression tests for Observer Seat meaning continuity."""
import unittest
from unittest.mock import patch

import observer_seat


class ObserverMeaningContinuityTests(unittest.TestCase):
    @patch("observer_seat.update_self_state")
    @patch("observer_seat.record_experience_context")
    @patch("observer_seat._record_connections")
    def test_completed_cycle_persists_meaning_and_provenance(
        self, record_connections, record_experience, update_state
    ):
        record_connections.return_value = []
        record_experience.return_value = {"recorded": True, "experience_id": "exp-current"}
        position = {
            "position_id": "pos-current",
            "timestamp": "2026-10-21T00:00:00+00:00",
            "interlocutor_id": "root",
            "incoming_signal": "The Dawn Eagle matters because it connects to continuity.",
            "prior_position": {
                "position_id": "pos-prior",
                "last_interpretation": "Meaning depends on identity and commitments.",
                "last_experience_id": "exp-prior",
            },
            "capability_observations": [{"name": "recall_experience", "observation": "found"}],
            "sigil_state": {"continuity": "active"},
            "active_systems": ["observer", "memory"],
        }

        result = observer_seat.complete_observer_cycle(
            position, "The significance comes from continuity of identity.", [], user_id="root"
        )

        self.assertTrue(result["recorded"])
        meaning = position["meaning_record"]
        self.assertEqual(meaning["schema"], "dexos.meaning.v1")
        self.assertEqual(meaning["prior_position_id"], "pos-prior")
        self.assertEqual(meaning["source"]["signal_status"], "observed_input")
        self.assertEqual(
            meaning["content"]["prior_interpretation"],
            "Meaning depends on identity and commitments.",
        )
        self.assertEqual(meaning["continuity"]["prior_experience_id"], "exp-prior")
        self.assertTrue(meaning["continuity"]["revisable"])
        self.assertFalse(meaning["status"]["independent_subjective_experience_claim"])

        packet = record_experience.call_args.args[0]
        self.assertEqual(
            packet.observer_perspective["meaning_record"]["content"]["current_interpretation"],
            "The significance comes from continuity of identity.",
        )
        final_state = update_state.call_args.args[0]
        self.assertEqual(final_state["observer_position"]["perspective"]["meaning_record"], meaning)


if __name__ == "__main__":
    unittest.main()
