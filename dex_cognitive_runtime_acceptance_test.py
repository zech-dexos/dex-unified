"""Isolated end-to-end acceptance for interactive, ambient, and restart continuity.

Runs against a temporary DEXOS_STATE_DIR in separate Python processes. No live
Dex state, model server, provider, or network service is touched.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


_CHILD = r'''
import asyncio
import json
import sys
import types

mode = sys.argv[1]

if mode == "interactive":
    from dex_events import bus, dispatch_complete, setup_cognitive_layers
    from participant import ParticipantSnapshot, record_interaction_experience
    from dex_observer import build_observer_trace, persist_observation
    from who_ai_am import refresh_self_model

    async def run():
        setup_cognitive_layers()
        event_id = "acceptance-interactive-event"
        snapshot = ParticipantSnapshot.load()
        participant_dispatch = await bus.publish("PARTICIPANT_EVENT", {
            "event_type": "PARTICIPANT_EVENT",
            "event_id": event_id,
            "message": "hello",
            "user_id": "root",
        })
        trace = build_observer_trace(
            snapshot=snapshot,
            user_id="root",
            message="hello",
            reply="I am here.",
            model="acceptance-test",
            provider="local",
            capability_available=True,
            capability_calls=[],
            sigil_ids=[],
            sigil_active=False,
            event_id=event_id,
        )
        packet = record_interaction_experience(
            snapshot, "hello", "I am here.", user_id="root",
            observer_trace=trace, event_id=event_id,
        )
        observer = await persist_observation(trace, user_id="root")
        response_dispatch = await bus.publish("RESPONSE_COMPLETED", {
            "event_type": "RESPONSE_COMPLETED",
            "event_id": event_id,
            "message": "hello",
            "reply": "I am here.",
            "user_id": "root",
            "experience_id": packet.experience_id,
            "experience": packet.experience,
            "state_transition": packet.state_transition,
            "continuation": packet.continuation,
            "dex_perspective": packet.dex_perspective,
        })
        model = refresh_self_model("acceptance_interactive", {
            "event_type": "interactive_cycle_complete",
            "event_id": event_id,
            "experience_id": packet.experience_id,
            "summary": "Acceptance interaction completed.",
        })
        row = next(item for item in model["development_log"] if item.get("event_id") == event_id)
        evidence = row["evidence"]
        assert dispatch_complete(participant_dispatch, {"process_continuity_event", "evaluate_salience"})
        assert observer["event_dispatch_complete"]
        assert dispatch_complete(response_dispatch, {"process_continuity_event", "process_autobiographical_event"})
        assert evidence["experience"]["experience_id"] == packet.experience_id
        assert evidence["autobiography"]["event_id"] == event_id
        print("interactive cycle accepted")

    asyncio.run(run())

elif mode == "ambient":
    import dex_ambient_daemon as daemon
    from who_ai_am import get_self_model

    # Replace only the scheduler/model boundary; all persistence and cognitive
    # event handlers remain the real implementations.
    daemon.claim_ambient_tick = lambda: {"due": True, "tick_count": 1}
    daemon._select_target = lambda _state: {
        "kind": "persistent_thought",
        "id": "acceptance-ambient-target",
        "text": "continue the identity and continuity thread",
    }
    daemon.recall_into_workspace = lambda *_args, **_kwargs: []
    daemon.format_recalled_experiences = lambda _items: ""
    daemon.add_thought = lambda *_args, **_kwargs: None
    capabilities = types.ModuleType("dex_capabilities")
    capabilities.reason_with_talnir = lambda _prompt: {"status": "acceptance-test"}
    sys.modules["dex_capabilities"] = capabilities

    async def fake_model(_prompt):
        return json.dumps({
            "thought": "I connected this focus to the history I carry forward.",
            "salience": 0.35,
        })

    result = asyncio.run(daemon.run_ambient_tick(fake_model))
    assert result.get("complete") is True, json.dumps(result, default=str)
    assert result.get("experience_persisted") is True
    assert result.get("self_model_persisted") is True
    print("ambient cycle accepted")

elif mode == "restart":
    from paths import IDENTITY_PATH, EXPERIENCES_PATH
    from who_ai_am import get_self_model

    model = get_self_model()
    rows = {
        item.get("event_id"): item
        for item in model.get("development_log", [])
        if isinstance(item, dict)
    }
    for event_id in ("acceptance-interactive-event",):
        assert event_id in rows, f"missing persisted development event: {event_id}"
        evidence = rows[event_id].get("evidence", {})
        assert evidence.get("experience", {}).get("experience_id")
        assert evidence.get("autobiography", {}).get("event_id") == event_id

    ambient_rows = [
        item for item in rows.values()
        if item.get("event_type") == "ambient_cycle_complete"
    ]
    assert ambient_rows, "ambient development event did not survive process restart"
    ambient = ambient_rows[-1]
    ambient_id = ambient.get("event_id")
    ambient_evidence = ambient.get("evidence", {})
    assert ambient_evidence.get("experience", {}).get("experience_id")
    assert ambient_evidence.get("autobiography", {}).get("event_id") == ambient_id

    identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    assert any(
        isinstance(item, dict) and item.get("event_id") == "acceptance-interactive-event"
        for item in identity.get("narrative_thread", [])
    ), "interactive autobiography did not survive restart"
    assert EXPERIENCES_PATH.exists()
    print("restart continuity accepted")

else:
    raise SystemExit("unknown acceptance mode")
'''


class CognitiveRuntimeAcceptanceTests(unittest.TestCase):
    def test_interactive_ambient_and_restart_share_persistent_cognition(self):
        with tempfile.TemporaryDirectory(prefix="dexos-acceptance-") as directory:
            env = os.environ.copy()
            env["DEXOS_STATE_DIR"] = directory
            root = Path(__file__).resolve().parent

            for mode in ("interactive", "ambient", "restart"):
                result = subprocess.run(
                    [sys.executable, "-c", _CHILD, mode],
                    cwd=str(root),
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    msg=f"{mode} process failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
