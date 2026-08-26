"""
amw.py — Phase 1: Active Mental Workspace (AMW)

A dedicated slot in SelfState for one concept Dex is "actively holding."
Mechanically this is: one record, a decay curve on focus_strength, and a
periodic refresh call that re-touches related knowledge-graph nodes and
appends a reflection. Nothing here is a claim about experience — it's a
priority-tagged record with a decay function, same category as a cache
entry with a TTL that gets extended on access.

Wiring (per dexos-core integration spec):
- kg_lookup: dexos.knowledge.graph_manager.get_related_knowledge_nodes(
      concept_identifier: str, max_depth: int = 2, min_relevance_score: float = 0.7
  ) -> List[Dict]   # each dict has at least an "id" key
- llm_reflect: dex-backend's gemini_client.py wrapper,
      generate_reflection_text(
          context: str, concept_being_held: str,
          prior_reflections: List[str] = None, desired_length: str = "medium"
      ) -> str

Both are injected as callables so dexos-core never imports the KG
implementation or an LLM client directly — no API keys, no provider
lock-in, no import cycles between dexos-core and dex-backend.

The periodic refresh_thought() loop itself is NOT run here — that's
Phase 3 (APE_Scheduler)'s job to call this on a timer. This module just
exposes the functions APE will call.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from self_state import SELF_STATE_PATH, load_self_state, update_self_state

FOCUS_DECAY_PER_REFRESH = 0.02  # simulated fatigue if resources are strained
FOCUS_FLOOR = 0.4
FOCUS_CEILING = 1.0
REFLECTION_HISTORY_WINDOW = 5   # how many prior reflections to pass as context

# get_related_knowledge_nodes(concept_identifier, max_depth=2, min_relevance_score=0.7) -> List[Dict]
KGLookup = Callable[..., List[Dict[str, Any]]]

# generate_reflection_text(context, concept_being_held, prior_reflections, desired_length) -> str
LLMReflect = Callable[..., str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_node_ids(kg_result: List[Dict[str, Any]]) -> List[str]:
    """get_related_knowledge_nodes returns full node dicts; AMW only stores pointers (IDs)."""
    return [node["id"] for node in kg_result if "id" in node]


def _build_context(self_state: Dict[str, Any]) -> str:
    """
    Internal helper (the '_get_current_dex_context()' from the design doc).
    Pulls a compact snapshot of SelfState relevant to reflection generation —
    active goals and recent narrative — so the LLM reflection call has
    grounding beyond just the bare concept name.
    """
    goals = self_state.get("active_goals_state", [])
    active_goal_descs = [g.get("description", "") for g in goals if g.get("status") == "active"]
    recent_narrative = self_state.get("narrative_thread", [])[-3:]
    narrative_summaries = [n.get("summary", "") for n in recent_narrative]

    parts = []
    if active_goal_descs:
        parts.append("Active goals: " + "; ".join(active_goal_descs))
    if narrative_summaries:
        parts.append("Recent narrative: " + "; ".join(narrative_summaries))
    return " | ".join(parts) if parts else "No additional context available."


def activate_thought(
    concept_identifier: str,
    description: str,
    duration_hint: Optional[str] = None,
    kg_lookup: Optional[KGLookup] = None,
    path: Path = SELF_STATE_PATH,
) -> Dict[str, Any]:
    """Begin actively holding a concept. Overwrites any prior active thought."""
    related_nodes = _extract_node_ids(kg_lookup(concept_identifier)) if kg_lookup else []
    now = _now_iso()

    delta = {
        "active_mental_workspace_state": {
            "is_active": True,
            "concept_identifier": concept_identifier,
            "description_snapshot": description,
            "activation_timestamp": now,
            "last_refresh_timestamp": now,
            "focus_strength": FOCUS_CEILING,
            "related_knowledge_nodes": related_nodes,
            "internal_reflections": [],
            "duration_hint": duration_hint,
        }
    }
    return update_self_state(delta, path=path)


def deactivate_thought(path: Path = SELF_STATE_PATH) -> Dict[str, Any]:
    """Release the active thought and drop its processing priority."""
    delta = {
        "active_mental_workspace_state": {
            "is_active": False,
            "focus_strength": 0.0,
        }
    }
    return update_self_state(delta, path=path)


def refresh_thought(
    kg_lookup: Optional[KGLookup] = None,
    llm_reflect: Optional[LLMReflect] = None,
    strained: bool = False,
    path: Path = SELF_STATE_PATH,
) -> Optional[Dict[str, Any]]:
    """
    Called periodically (by APE_Scheduler, Phase 3) while a thought is active.
    Re-touches related KG nodes, generates a new reflection via the injected
    LLM callable, updates timestamps, and applies focus decay only if
    `strained` (e.g. resource pressure) — otherwise focus stays pinned near
    the ceiling.

    Returns the updated state, or None if there's no active thought.
    """
    current = load_self_state(path)
    amw = current.get("active_mental_workspace_state", {})
    if not amw.get("is_active"):
        return None

    concept = amw["concept_identifier"]
    related_nodes = (
        _extract_node_ids(kg_lookup(concept)) if kg_lookup else amw.get("related_knowledge_nodes", [])
    )

    prior_reflections = [
        r["reflection"] for r in amw.get("internal_reflections", [])[-REFLECTION_HISTORY_WINDOW:]
    ]

    if llm_reflect:
        reflection_text = llm_reflect(
            context=_build_context(current),
            concept_being_held=concept,
            prior_reflections=prior_reflections,
            desired_length="medium",
        )
    else:
        reflection_text = f"Re-examined '{concept}' at {_now_iso()}."

    new_strength = amw.get("focus_strength", FOCUS_CEILING)
    new_strength = max(FOCUS_FLOOR, new_strength - FOCUS_DECAY_PER_REFRESH) if strained else FOCUS_CEILING

    reflections = list(amw.get("internal_reflections", []))
    reflections.append({"timestamp": _now_iso(), "reflection": reflection_text})

    delta = {
        "active_mental_workspace_state": {
            "last_refresh_timestamp": _now_iso(),
            "focus_strength": new_strength,
            "related_knowledge_nodes": related_nodes,
            "internal_reflections": reflections,
        }
    }
    return update_self_state(delta, path=path)


def report_active_thought_state(path: Path = SELF_STATE_PATH) -> str:
    """Human-readable summary of what's currently being held, if anything."""
    current = load_self_state(path)
    amw = current.get("active_mental_workspace_state", {})
    if not amw.get("is_active"):
        return "No active thought currently held."

    recent = amw.get("internal_reflections", [])[-3:]
    recent_lines = "\n".join(f"  - {r['reflection']}" for r in recent) or "  (none yet)"
    return (
        f"Holding: {amw['concept_identifier']}\n"
        f"Focus strength: {amw.get('focus_strength')}\n"
        f"Active since: {amw.get('activation_timestamp')}\n"
        f"Last refreshed: {amw.get('last_refresh_timestamp')}\n"
        f"Recent reflections:\n{recent_lines}"
    )


if __name__ == "__main__":
    test_path = Path("self_state.test.json")
    if test_path.exists():
        test_path.unlink()

    def test_kg_lookup(concept_id: str, max_depth: int = 2, min_relevance_score: float = 0.7) -> List[Dict[str, Any]]:
        return [
            {"id": f"node_{concept_id}_1", "type": "entity", "content": "test", "relation_to_concept": "IS_TYPE_OF"},
            {"id": f"node_{concept_id}_2", "type": "attribute", "content": "test", "relation_to_concept": "HAS_ATTRIBUTE"},
        ]

    def test_llm_reflect(context: str, concept_being_held: str, prior_reflections=None, desired_length="medium") -> str:
        prior_reflections = prior_reflections or []
        return f"test_reflection on {concept_being_held} (prior_count={len(prior_reflections)}, ctx={'yes' if context else 'no'})"

    s = activate_thought(
        "test_concept_alpha",
        "A test concept for AMW verification.",
        duration_hint="1 hour",
        kg_lookup=test_kg_lookup,
        path=test_path,
    )
    amw = s["active_mental_workspace_state"]
    assert amw["is_active"] is True
    assert amw["focus_strength"] == 1.0
    assert amw["related_knowledge_nodes"] == ["node_test_concept_alpha_1", "node_test_concept_alpha_2"]

    s = refresh_thought(kg_lookup=test_kg_lookup, llm_reflect=test_llm_reflect, strained=False, path=test_path)
    refl = s["active_mental_workspace_state"]["internal_reflections"]
    assert s["active_mental_workspace_state"]["focus_strength"] == 1.0
    assert len(refl) == 1
    assert "test_concept_alpha" in refl[0]["reflection"]
    assert "prior_count=0" in refl[0]["reflection"]

    s = refresh_thought(kg_lookup=test_kg_lookup, llm_reflect=test_llm_reflect, strained=True, path=test_path)
    refl = s["active_mental_workspace_state"]["internal_reflections"]
    assert abs(s["active_mental_workspace_state"]["focus_strength"] - 0.98) < 1e-9
    assert len(refl) == 2
    assert "prior_count=1" in refl[1]["reflection"]

    # no-callable fallback path still works
    s2_path = Path("self_state.test2.json")
    if s2_path.exists():
        s2_path.unlink()
    activate_thought("fallback_concept", "no callables provided", path=s2_path)
    s2 = refresh_thought(path=s2_path)
    assert "Re-examined" in s2["active_mental_workspace_state"]["internal_reflections"][0]["reflection"]
    s2_path.unlink()

    report = report_active_thought_state(path=test_path)
    assert "test_concept_alpha" in report

    s = deactivate_thought(path=test_path)
    assert s["active_mental_workspace_state"]["is_active"] is False
    assert report_active_thought_state(path=test_path) == "No active thought currently held."

    test_path.unlink()
    print("amw.py: all checks passed")
