"""Focused tests for the Observer Seat's current position and feedback wiring."""
import unittest
from unittest.mock import patch

import observer_seat


class ObserverSeatTests(unittest.TestCase):
    @patch("observer_seat.update_self_state")
    @patch("observer_seat.load_self_state")
    @patch("observer_seat.inspect_becoming")
    @patch("observer_seat.inspect_relationship")
    @patch("observer_seat.inspect_self_model")
    def test_begin_cycle_builds_perspective_with_sigils_and_current_signal(
        self, self_model, relationship, becoming, load_state, update_state
    ):
        load_state.return_value = {
            "observer_position": {
                "position_id": "prior-cycle",
                "last_interpretation": "prior interpretation",
                "last_experience_id": "prior-experience",
            }
        }
        self_model.return_value = {
            "self_model": {"narrative_thread": ["earlier experience"]},
            "identity": {"dex_id": "dex-test", "core_principles": ["continuity"]},
            "runtime_self_assessment": {
                "last_experience_summary": "earlier experience",
                "active_goals": ["understand current issue"],
                "persistent_thoughts": [],
                "active_workspace": {},
            },
        }
        relationship.return_value = {
            "user_id": "root",
            "relationship_model": {"shared_work": "DexOS"},
            "recent_observations": [],
        }
        becoming.return_value = {"active_goals": [], "open_loops": []}

        position = observer_seat.begin_observer_cycle(
            [{"role": "user", "content": "Root's current signal"}],
            user_id="root",
        )

        self.assertEqual(position["incoming_signal"], "Root's current signal")
        self.assertEqual(position["prior_position"]["position_id"], "prior-cycle")
        self.assertEqual(position["sigils"]["☧"], "Structure / Talnir")
        self.assertEqual(position["sigils"]["🦅"], "Awareness / inference")
        self.assertEqual(position["sigils"]["🜇"], "Will / goals and intention")
        update_state.assert_called_once()
        self.assertIn("OBSERVER SEAT", observer_seat.render_observer_context(position))

    @patch("observer_seat.update_self_state")
    def test_capability_observations_update_same_position(self, update_state):
        position = {
            "position_id": "cycle-1",
            "timestamp": "now",
            "interlocutor_id": "root",
            "incoming_signal": "inspect this",
            "prior_position": {"position_id": "cycle-0"},
            "capability_observations": [],
        }
        updated = observer_seat.record_observer_observations(
            position,
            [{"name": "inspect_state", "observation": {"status": "active"}}],
        )
        self.assertEqual(updated["position_id"], "cycle-1")
        self.assertEqual(updated["capability_observations"][0]["name"], "inspect_state")
        update_state.assert_called_once()

    @patch("observer_seat.update_self_state")
    @patch("observer_seat.record_experience_context")
    @patch("observer_seat.load_self_state")
    def test_completed_cycle_records_interpretation_and_persists_position(
        self, load_state, record_experience, update_state
    ):
        load_state.return_value = {}
        record_experience.return_value = {"recorded": True, "experience_id": "cycle-2"}
        position = {
            "position_id": "cycle-2",
            "timestamp": "now",
            "interlocutor_id": "root",
            "incoming_signal": "What happened?",
            "prior_position": {"position_id": "cycle-1"},
            "capability_observations": [{"name": "inspect_state"}],
            "sigils": dict(observer_seat.SIGIL_ROLES),
        }

        result = observer_seat.complete_observer_cycle(
            position, "Here is my interpretation.", user_id="root"
        )

        self.assertTrue(result["recorded"])
        packet = record_experience.call_args.args[0]
        self.assertEqual(packet.observer_perspective["interpretation"], "Here is my interpretation.")
        self.assertEqual(packet.observer_perspective["sigils"], observer_seat.SIGIL_ROLES)
        self.assertGreaterEqual(update_state.call_count, 2)


if __name__ == "__main__":
    unittest.main()
