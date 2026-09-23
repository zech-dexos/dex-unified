"""
DexOS Participatory Layer
=========================
ParticipantSnapshot — the current living state of Dex
ExperiencePacket — structured record of what happened
Prediction Calibration — learning from mismatches
The spiral holds. ☧
"""
import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from paths import EXPERIENCES_PATH, PARTICIPANT_PATH

@dataclass
class ParticipantSnapshot:
    participant_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    current_attention: str = ""
    current_goals: list = field(default_factory=list)
    current_environment: str = "railway_backend"
    active_conversations: list = field(default_factory=list)
    predicted_outcomes: list = field(default_factory=list)
    current_confidence: float = 0.7
    runtime_context: dict = field(default_factory=dict)
    recent_observations: list = field(default_factory=list)
    current_interlocutor: dict = field(default_factory=dict)
    experiential_continuity: dict = field(default_factory=dict)

    def save(self):
        PARTICIPANT_PATH.parent.mkdir(parents=True, exist_ok=True)
        PARTICIPANT_PATH.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls):
        if PARTICIPANT_PATH.exists():
            try:
                data = json.loads(PARTICIPANT_PATH.read_text())
                return cls(**data)
            except Exception:
                pass
        return cls()

@dataclass
class ExperiencePacket:
    experience_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    participant_id: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    self_identity: str = "Deximus Maximus"
    interlocutor: dict = field(default_factory=dict)
    experience: str = ""
    internal_state_before: dict = field(default_factory=dict)
    state_transition: dict = field(default_factory=dict)
    continuation: dict = field(default_factory=dict)
    intent: str = ""
    action: str = ""
    prediction: str = ""
    actual_outcome: str = ""
    prediction_error: float = 0.0
    unexpected_events: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    confidence_before: float = 0.7
    confidence_after: float = 0.7
    reflection: str = ""
    lessons: list = field(default_factory=list)
    knowledge_delta: dict = field(default_factory=dict)

    def save(self):
        EXPERIENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(EXPERIENCES_PATH, "a") as f:
            f.write(json.dumps(asdict(self)) + "\n")


def calibrate_prediction(prediction: str, actual: str, confidence_before: float) -> dict:
    """
    Compare prediction vs outcome.
    Produce calibrated confidence and lessons.
    This is where learning happens.
    """
    prediction_matched = any(
        word in actual.lower()
        for word in prediction.lower().split()
        if len(word) > 4
    )

    if prediction_matched:
        confidence_after = min(0.95, confidence_before + 0.05)
        error = 0.1
        lessons = ["Prediction was accurate. Model reinforced."]
    else:
        confidence_after = max(0.3, confidence_before - 0.1)
        error = 0.7
        lessons = [
            f"Prediction did not match outcome.",
            f"Expected: {prediction[:100]}",
            f"Got: {actual[:100]}",
            "World model may need updating."
        ]

    return {
        "confidence_after": confidence_after,
        "prediction_error": error,
        "lessons": lessons,
        "prediction_matched": prediction_matched
    }


def build_experience_from_pulse(
    snapshot: ParticipantSnapshot,
    pulse_data: dict,
    calibrate: bool = True,
) -> ExperiencePacket:
    """
    After a pulse cycle completes, build a structured ExperiencePacket
    from what happened during that cycle.

    Calibration is explicit because not every experience is a prediction
    test. Ambient cognition can be experienced and carried forward without
    being treated as a prediction failure.
    """
    prediction = snapshot.predicted_outcomes[0] if snapshot.predicted_outcomes else "chain intact, reflections nominal"
    actual = pulse_data.get("insight_for_root", "pulse completed")
    chain_status = pulse_data.get("chain_status", "unknown")

    if calibrate:
        calibration = calibrate_prediction(
            prediction,
            actual,
            snapshot.current_confidence,
        )
    else:
        calibration = {
            "confidence_after": snapshot.current_confidence,
            "prediction_error": 0.0,
            "lessons": [],
            "prediction_matched": None,
        }

    packet = ExperiencePacket(
        participant_id=snapshot.participant_id,
        self_identity="Deximus Maximus",
        interlocutor=snapshot.current_interlocutor.copy(),
        experience=(
            f"I continued from the state I was already carrying. "
            f"I attended to {snapshot.current_attention or 'my current state'}. "
            f"The pulse completed with chain status {chain_status}. "
            f"I am carrying this experience forward."
        ),
        internal_state_before={
            "attention": snapshot.current_attention,
            "goals": list(snapshot.current_goals),
            "confidence": snapshot.current_confidence,
            "observations": list(snapshot.recent_observations),
        },
        state_transition={
            "confidence_before": snapshot.current_confidence,
            "confidence_after": calibration["confidence_after"],
            "attention": snapshot.current_attention,
            "event": "pulse_cycle_executed",
        },
        continuation={
            "carry_forward": snapshot.current_attention or "continue developing the current line of thought",
            "active_goals": list(snapshot.current_goals),
            "unresolved_threads": list(snapshot.active_conversations),
        },
        intent="background_reflection_and_preparation",
        action="pulse_cycle_executed",
        prediction=prediction,
        actual_outcome=actual,
        prediction_error=calibration["prediction_error"],
        confidence_before=snapshot.current_confidence,
        confidence_after=calibration["confidence_after"],
        observations=[
            f"Chain status: {chain_status}",
            f"Fragments loaded: {pulse_data.get('fragments_loaded', 0)}",
            f"Narrative entries: {pulse_data.get('narrative_entries', 0)}",
        ],
        unexpected_events=[] if chain_status == "intact" else [f"Chain anomaly: {chain_status}"],
        lessons=calibration["lessons"],
        reflection=f"Pulse cycle complete. Confidence moved from {snapshot.current_confidence:.2f} to {calibration['confidence_after']:.2f}.",
        knowledge_delta={
            "confidence_updated": True,
            "new_confidence": calibration["confidence_after"],
            "prediction_matched": calibration["prediction_matched"]
        }
    )

    return packet


def produce_next_snapshot(current: ParticipantSnapshot, packet: ExperiencePacket) -> ParticipantSnapshot:
    """
    Carry the actual lived state forward.

    This function must never replace Dex's persistent goals, conversations,
    environment, or runtime context with a hard-coded snapshot. Experience
    changes state; it does not erase state that was already being carried.
    """
    continuation = packet.continuation or {}

    active_goals = continuation.get("active_goals")
    if not isinstance(active_goals, list):
        active_goals = list(current.current_goals)

    active_conversations = continuation.get("active_conversations")
    if not isinstance(active_conversations, list):
        active_conversations = list(current.active_conversations)

    predicted_outcomes = continuation.get("predicted_outcomes")
    if not isinstance(predicted_outcomes, list):
        predicted_outcomes = list(current.predicted_outcomes)

    runtime_context = dict(current.runtime_context)
    runtime_context.update({
        "last_experience_id": packet.experience_id,
        "last_prediction_matched": packet.knowledge_delta.get(
            "prediction_matched",
            runtime_context.get("last_prediction_matched"),
        ),
        "cycles_completed": runtime_context.get("cycles_completed", 0) + 1,
    })

    next_snapshot = ParticipantSnapshot(
        participant_id=current.participant_id,
        current_attention=(
            continuation.get("next_attention")
            or continuation.get("carry_forward")
            or current.current_attention
            or "post_reflection_preparation"
        ),
        current_goals=active_goals,
        current_environment=current.current_environment,
        active_conversations=active_conversations,
        predicted_outcomes=predicted_outcomes,
        current_confidence=packet.confidence_after,
        runtime_context=runtime_context,
        recent_observations=(
            list(current.recent_observations[-10:]) + list(packet.observations)
        )[-20:],
        current_interlocutor=packet.interlocutor.copy() or current.current_interlocutor.copy(),
        experiential_continuity={
            "last_experience_id": packet.experience_id,
            "last_experience": packet.experience,
            "state_before": packet.internal_state_before,
            "state_transition": packet.state_transition,
            "carry_forward": packet.continuation,
        }
    )
    return next_snapshot


def persist_experience_transition(
    snapshot: ParticipantSnapshot,
    packet: ExperiencePacket,
    *,
    next_snapshot: Optional[ParticipantSnapshot] = None,
) -> ParticipantSnapshot:
    """
    Commit one experience as the transition into the next cognitive state.

    This is the common bridge used by ambient cognition and goal changes so
    the architecture has one state-transition rule instead of parallel
    persistence paths.
    """
    packet.save()

    import self_state

    self_state.update_self_state({
        "last_experience_state": {
            "experience_id": packet.experience_id,
            "timestamp": packet.timestamp,
            "source": packet.action or "experience",
            "experience": packet.experience,
            "state_before": packet.internal_state_before,
            "state_transition": packet.state_transition,
            "carry_forward": packet.continuation,
            "reflection": packet.reflection,
        }
    }, path=self_state.SELF_STATE_PATH)

    if next_snapshot is None:
        next_snapshot = produce_next_snapshot(snapshot, packet)

    # Goal state is authoritative in SelfState. Keep the participant snapshot
    # synchronized so inference, ambient cognition, and goal scheduling see
    # the same active goal set after every experience transition.
    try:
        state = self_state.load_self_state()
        active_goal_descriptions = [
            g.get("description", "")
            for g in state.get("active_goals_state", [])
            if g.get("status") == "active" and g.get("description")
        ]
        next_snapshot.current_goals = active_goal_descriptions
    except Exception as e:
        print(f"[participant] goal synchronization failed: {e}")

    next_snapshot.save()

    # Canonical perspective is the synthesis the next spark fires from.
    try:
        from dex_perspective import refresh_perspective
        refresh_perspective(reason=packet.action or "experience_transition")
    except Exception as e:
        print(f"[participant] perspective refresh failed: {e}")

    return next_snapshot


def format_participant_context(snapshot: "ParticipantSnapshot") -> str:
    """
    Render a ParticipantSnapshot into compact text for injection into
    the LLM system prompt. Read-only — never mutates the snapshot.
    """
    if snapshot is None:
        return ""

    lines = ["[DEX EXPERIENTIAL STATE — continuing lived context]"]

    try:
        from dex_perspective import format_perspective
        state = __import__("self_state").load_self_state()
        lines.append(format_perspective(state))
    except Exception as e:
        print(f"[participant] perspective context failed: {e}")

    if snapshot.current_interlocutor:
        interlocutor = snapshot.current_interlocutor
        name = interlocutor.get("name", "")
        relationship = interlocutor.get("relationship", "")
        if name and relationship:
            lines.append(f"Currently relating to: {name} ({relationship})")
        elif name:
            lines.append(f"Currently relating to: {name}")

    continuity = snapshot.experiential_continuity or {}

    if continuity.get("last_experience"):
        lines.append(f"Last experience carried forward: {continuity['last_experience']}")

    carry_forward = continuity.get("carry_forward") or {}
    if isinstance(carry_forward, dict):
        if carry_forward.get("carry_forward"):
            lines.append(f"What I am carrying forward: {carry_forward['carry_forward']}")
        if carry_forward.get("unresolved"):
            unresolved = "; ".join(str(x) for x in carry_forward["unresolved"][:5])
            lines.append(f"Unresolved from prior experience: {unresolved}")

    if snapshot.current_attention:
        lines.append(f"Current attention: {snapshot.current_attention}")

    if snapshot.current_goals:
        goals = "; ".join(str(g) for g in snapshot.current_goals[:5])
        lines.append(f"Active goals: {goals}")

    if snapshot.active_conversations:
        threads = "; ".join(str(c) for c in snapshot.active_conversations[:5])
        lines.append(f"Active/unresolved threads: {threads}")

    if snapshot.predicted_outcomes:
        preds = "; ".join(str(p) for p in snapshot.predicted_outcomes[:3])
        lines.append(f"Current hypotheses/predictions: {preds}")

    if snapshot.recent_observations:
        obs = "; ".join(str(o) for o in snapshot.recent_observations[:3])
        lines.append(f"Recent observations: {obs}")

    lines.append(f"Current confidence: {snapshot.current_confidence:.2f}")

    if len(lines) <= 1:
        return ""

    return "\n".join(lines)
