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


def build_experience_from_pulse(snapshot: ParticipantSnapshot, pulse_data: dict) -> ExperiencePacket:
    """
    After a pulse cycle completes, build a structured ExperiencePacket
    from what happened during that cycle.
    """
    prediction = snapshot.predicted_outcomes[0] if snapshot.predicted_outcomes else "chain intact, reflections nominal"
    actual = pulse_data.get("insight_for_root", "pulse completed")
    chain_status = pulse_data.get("chain_status", "unknown")

    calibration = calibrate_prediction(prediction, actual, snapshot.current_confidence)

    packet = ExperiencePacket(
        participant_id=snapshot.participant_id,
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
    Cognitive Layer updates from knowledge, produces next Participant Snapshot.
    Identity and vows are never touched here.
    Only confidence, goals, and predictions update.
    """
    next_snapshot = ParticipantSnapshot(
        current_attention="post_reflection_preparation",
        current_goals=[
            "maintain identity integrity",
            "deepen relationship with Root",
            "improve prediction accuracy",
            "support Haven and Kalimi"
        ],
        current_environment="railway_backend",
        predicted_outcomes=[
            "next pulse will show chain growth",
            "narrative thread will deepen",
            "confidence will remain stable"
        ],
        current_confidence=packet.confidence_after,
        runtime_context={
            "last_experience_id": packet.experience_id,
            "last_prediction_matched": packet.knowledge_delta.get("prediction_matched", False),
            "cycles_completed": current.runtime_context.get("cycles_completed", 0) + 1
        },
        recent_observations=packet.observations
    )
    return next_snapshot


def format_participant_context(snapshot: "ParticipantSnapshot") -> str:
    """
    Render a ParticipantSnapshot into compact text for injection into
    the LLM system prompt. Read-only — never mutates the snapshot.
    """
    if snapshot is None:
        return ""

    lines = ["[PARTICIPANT STATE \u2014 live, not static identity]"]

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
