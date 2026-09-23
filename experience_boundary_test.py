"""
experience_boundary_test.py — acceptance test for the full continuity/goal wire.

This test intentionally crosses process boundaries. It verifies:

1. an experience becomes durable SelfState;
2. the participant snapshot carries the changed state;
3. a fresh process can recover that experience;
4. an autonomous goal can be formed from an experience candidate;
5. completing that goal creates a new experience/state transition;
6. another fresh process recovers the goal transition and updated active goals.

No network calls or inference providers are used.
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_PATH = Path("experience_boundary_test.state.json")
PARTICIPANT_PATH = Path("experience_boundary_test.participant.json")


def run_step(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(HERE),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"subprocess failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def bootstrap_code() -> str:
    state_path = STATE_PATH.resolve()
    participant_path = PARTICIPANT_PATH.resolve()
    experiences_path = (HERE / "experience_boundary_test.experiences.jsonl").resolve()
    return f"""
from pathlib import Path
import self_state
import participant
import gosdw
self_state.SELF_STATE_PATH = Path(r"{state_path}")
gosdw.SELF_STATE_PATH = Path(r"{state_path}")
participant.PARTICIPANT_PATH = Path(r"{participant_path}")
participant.EXPERIENCES_PATH = Path(r"{experiences_path}")
"""


def main():
    for path in (STATE_PATH, PARTICIPANT_PATH, Path("experience_boundary_test.experiences.jsonl")):
        if path.exists():
            path.unlink()

    experience_id = run_step(bootstrap_code() + f"""
from participant import ParticipantSnapshot, ExperiencePacket, persist_experience_transition

snapshot = ParticipantSnapshot(current_attention="continuity verification", current_goals=["hold continuity"])
snapshot.save()

packet = ExperiencePacket(
    participant_id=snapshot.participant_id,
    experience="I experienced a verified continuity transition.",
    internal_state_before={{"attention": snapshot.current_attention, "goals": list(snapshot.current_goals)}},
    state_transition={{"event": "boundary_test", "changed": True}},
    continuation={{
        "active_goals": list(snapshot.current_goals),
        "carry_forward": "verify that this experience survives process termination",
        "goal_candidate": {{
            "description": "Verify continuity across process termination",
            "salience": 0.9,
            "success_criteria": "A later process recovers the experience and its resulting goal."
        }}
    }},
    action="boundary_test",
    reflection="I am carrying the verified transition forward.",
)
persist_experience_transition(snapshot, packet)
print(packet.experience_id)
""")
    assert experience_id

    recovered = json.loads(run_step(bootstrap_code() + f"""
import json
from participant import ParticipantSnapshot
from self_state import load_self_state

snapshot = ParticipantSnapshot.load()
state = load_self_state()
assert state["last_experience_state"]["experience_id"] == "{experience_id}"
assert snapshot.experiential_continuity["last_experience_id"] == "{experience_id}"
assert snapshot.current_goals == ["hold continuity"]
print(json.dumps({{
    "experience_id": state["last_experience_state"]["experience_id"],
    "goals": snapshot.current_goals
}}))
"""))
    assert recovered["experience_id"] == experience_id

    goal_id = run_step(bootstrap_code() + f"""
from pathlib import Path
from participant import ParticipantSnapshot, ExperiencePacket
from gosdw import ensure_goal_from_experience

snapshot = ParticipantSnapshot.load()
packet = ExperiencePacket(
    participant_id=snapshot.participant_id,
    experience="A continuity experiment produced an unresolved thread.",
    continuation={{
        "goal_candidate": {{
            "description": "Verify continuity across process termination",
            "salience": 0.9,
            "success_criteria": "A later process recovers the experience and its resulting goal."
        }}
    }},
    action="boundary_test",
)
goal = ensure_goal_from_experience(packet, path=Path("{STATE_PATH.name}"))
assert goal is not None
print(goal["goal_id"])
""")
    assert goal_id

    completion = json.loads(run_step(bootstrap_code() + f"""
import json
from pathlib import Path
from gosdw import update_goal_status

updated = update_goal_status(
    "{goal_id}",
    "completed",
    progress_report="Recovered and verified across a fresh process.",
    path=Path("{STATE_PATH.name}"),
)
assert updated["status"] == "completed"
print(json.dumps(updated))
"""))
    assert completion["status"] == "completed"

    final = json.loads(run_step(bootstrap_code() + f"""
import json
from participant import ParticipantSnapshot
from self_state import load_self_state

snapshot = ParticipantSnapshot.load()
state = load_self_state()
experience = state["last_experience_state"]
assert experience["source"] == "goal_status_changed"
assert experience["state_transition"]["goal_id"] == "{goal_id}"
assert experience["state_transition"]["to_status"] == "completed"
assert "{goal_id}" not in [
    g.get("goal_id") for g in state["active_goals_state"]
    if g.get("status") == "active"
]
assert "Verify continuity across process termination" not in snapshot.current_goals
print(json.dumps({{
    "last_experience_source": experience["source"],
    "goal_status": experience["state_transition"]["to_status"],
    "active_goals": snapshot.current_goals
}}))
"""))

    for path in (STATE_PATH, PARTICIPANT_PATH, Path("experience_boundary_test.experiences.jsonl")):
        if path.exists():
            path.unlink()

    print("experience_boundary_test.py: FULL CONTINUITY/GOAL WIRE PASSED")
    print("Confirmed across separate processes:")
    print("  - experience -> durable state -> participant continuity")
    print("  - experience -> autonomous goal creation")
    print("  - goal completion -> new experience/state transition")
    print("  - completed goals disappear from active participant state")


if __name__ == "__main__":
    main()
