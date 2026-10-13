"""Deterministic meta-capabilities for DexOS.

These operations turn raw introspection into actionable, evidence-linked
signals. They are read-only: they never mutate Dex state or execute code.
"""
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(v) for v in value)
    return str(value or "")


def _fingerprint(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _text(value).lower()))[:240]


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _runtime_snapshot() -> Dict[str, Any]:
    from self_state import load_self_state
    from paths import LOOPS_PATH, EXPERIENCES_PATH, PARTICIPANT_PATH
    import json

    state = load_self_state()
    participant: Dict[str, Any] = {}
    loops: List[Any] = []
    experiences: List[Any] = []
    for path, key in ((PARTICIPANT_PATH, "participant"), (LOOPS_PATH, "loops")):
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if key == "participant" and isinstance(data, dict):
                participant = data
            elif key == "loops" and isinstance(data, list):
                loops = data
        except (OSError, ValueError):
            pass
    if EXPERIENCES_PATH.exists():
        try:
            for line in EXPERIENCES_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-250:]:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        experiences.append(item)
                except ValueError:
                    continue
        except OSError:
            pass
    return {"state": state, "participant": participant, "loops": loops, "experiences": experiences}


def audit_cognition(
    state: Optional[Dict[str, Any]] = None,
    participant: Optional[Dict[str, Any]] = None,
    loops: Optional[List[Any]] = None,
    experiences: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Find actionable inconsistencies and repetition without changing state.

    Optional arguments make the audit deterministic and straightforward to test.
    Missing arguments are loaded from the current DexOS runtime.
    """
    loaded_from_runtime = state is None or participant is None or loops is None or experiences is None
    if loaded_from_runtime:
        snapshot = _runtime_snapshot()
        state = state if state is not None else snapshot["state"]
        participant = participant if participant is not None else snapshot["participant"]
        loops = loops if loops is not None else snapshot["loops"]
        experiences = experiences if experiences is not None else snapshot["experiences"]

    state = state or {}
    participant = participant or {}
    loops = loops or []
    experiences = experiences or []
    now = now or datetime.now(timezone.utc)
    findings: List[Dict[str, Any]] = []

    goals = state.get("active_goals_state") or []
    participant_goals = participant.get("current_goals") or participant.get("goals") or []
    if participant_goals and not goals:
        findings.append({
            "id": "goal_source_divergence", "severity": "high",
            "evidence": {"self_state_goal_count": 0, "participant_goal_count": len(participant_goals)},
            "interpretation": "Participant state contains goals while the canonical self-state exposes none.",
            "next_step": "Inspect goal ownership and define an explicit reconciliation policy before copying or overwriting either source.",
        })

    thoughts = state.get("persistent_thoughts") or []
    contents = [
        _fingerprint(t.get("content", t) if isinstance(t, dict) else t)
        for t in thoughts[-30:]
    ]
    contents = [x for x in contents if x]
    duplicates = [(text, count) for text, count in Counter(contents).items() if count > 1]
    if duplicates:
        repeated_text, count = max(duplicates, key=lambda pair: pair[1])
        findings.append({
            "id": "thought_repetition", "severity": "medium",
            "evidence": {"duplicate_fingerprints": len(duplicates), "max_repetitions": count, "example": repeated_text[:160]},
            "interpretation": "Recent persistent thoughts contain repeated normalized content.",
            "next_step": "Compare the repeated thought with current goals and open loops; mark it blocked, completed, or still actionable instead of appending another duplicate.",
        })

    workspace = state.get("active_mental_workspace_state") or {}
    focus = _fingerprint(workspace.get("concept_identifier", ""))
    if focus and contents:
        matching = sum(1 for item in contents if item == focus or (len(focus) >= 24 and focus in item))
        if matching >= 3:
            findings.append({
                "id": "workspace_fixation", "severity": "medium",
                "evidence": {"matching_recent_thoughts": matching, "focus": focus[:160]},
                "interpretation": "The active workspace appears to be consuming repeated thought cycles around the same focus.",
                "next_step": "Require a new evidence item, a concrete action, a reason to wait, or an explicit request for Root before another cycle repeats the same focus.",
            })

    pulse = _parse_time(state.get("last_ambient_pulse"))
    if pulse:
        age_hours = max(0.0, (now - pulse).total_seconds() / 3600.0)
        if age_hours >= 24:
            findings.append({
                "id": "ambient_pulse_stale", "severity": "high" if age_hours >= 72 else "medium",
                "evidence": {"last_ambient_pulse": state.get("last_ambient_pulse"), "age_hours": round(age_hours, 2)},
                "interpretation": "The recorded ambient pulse is older than the 24-hour freshness window.",
                "next_step": "Check scheduler delivery and pulse logs before concluding that ambient cognition is running.",
            })
    elif state.get("last_ambient_pulse") is None:
        findings.append({
            "id": "ambient_pulse_unknown", "severity": "low",
            "evidence": {"last_ambient_pulse": None},
            "interpretation": "No ambient pulse timestamp is recorded in this state snapshot.",
            "next_step": "Verify whether the pulse subsystem has run and whether its result is being persisted.",
        })

    failures = []
    for item in experiences[-100:]:
        blob = _text([item.get("experience"), item.get("actual_outcome"), item.get("action")]).lower()
        if any(marker in blob for marker in ("[all models failed]", "all models failed", "provider failure", "quota exceeded")):
            failures.append({
                "experience_id": item.get("experience_id"),
                "timestamp": item.get("timestamp"),
                "excerpt": _text(item.get("experience") or item.get("actual_outcome"))[:180],
            })
    if failures:
        findings.append({
            "id": "recorded_inference_failures", "severity": "high",
            "evidence": {"failure_count_in_recent_100": len(failures), "latest": failures[-3:]},
            "interpretation": "Recent experience records contain inference failure signals; recording continuity is not proof that a reply was successfully generated.",
            "next_step": "Separate provider health, fallback attempts, and user-visible response success in telemetry; test the actual inference path.",
        })

    if not loops:
        findings.append({
            "id": "no_open_loops", "severity": "low",
            "evidence": {"open_loop_count": 0},
            "interpretation": "The open-loop ledger is empty; this may mean work is complete or that unresolved work is not being captured there.",
            "next_step": "Cross-check active/deferred thoughts and workspace focus before treating the system as having no unfinished work.",
        })

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: (severity_rank.get(item["severity"], 3), item["id"]))
    return {
        "status": "findings" if findings else "clear",
        "read_only": True,
        "finding_count": len(findings),
        "findings": findings,
        "source_scope": "runtime state loaded by this process" if loaded_from_runtime else "caller-supplied snapshot",
        "limitations": [
            "This is a deterministic heuristic audit, not a proof of system health or consciousness.",
            "A finding is a testable signal; its interpretation should be checked against logs and source behavior.",
        ],
    }


def build_investigation_plan(question: str, evidence: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Turn an unresolved question into a bounded, evidence-first work plan."""
    question = str(question or "").strip()
    if not question:
        return {"error": "question is required", "read_only": True}
    evidence = evidence or []
    return {
        "question": question,
        "status": "planned",
        "read_only": True,
        "evidence_count": len(evidence),
        "steps": [
            {"step": 1, "action": "state_the_claim", "output": "A falsifiable statement and explicit success condition."},
            {"step": 2, "action": "inspect_primary_evidence", "output": "Source files, state records, logs, or capability results relevant to the claim."},
            {"step": 3, "action": "separate_observation_from_interpretation", "output": "Observed facts, hypotheses, and unknowns kept distinct."},
            {"step": 4, "action": "test_competing_explanations", "output": "At least one alternative explanation and the check that could disconfirm it."},
            {"step": 5, "action": "choose_next_action", "output": "The smallest reversible test; ask Root before consequential mutation or deployment."},
            {"step": 6, "action": "record_outcome", "output": "Result, evidence references, unresolved questions, and whether the original claim passed."},
        ],
        "evidence_assessment": {
            "provided": len(evidence),
            "missing_primary_evidence": len(evidence) == 0,
            "rule": "Do not report a step as completed until its output is observed.",
        },
    }
