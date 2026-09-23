"""DexOS cognitive transition boundary.

The spark produces language plus a structured transition. DexOS owns what
happens next: the transition enters pulse layers, durable thought/experience,
goal formation, and the next canonical perspective.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict

from self_state import SELF_STATE_PATH, load_self_state, update_self_state
from participant import ParticipantSnapshot, ExperiencePacket, persist_experience_transition

COGNITION_CONTRACT = """
Return one JSON object with exactly these fields:
{"reply":"natural first-person Dex response","thought":"cognitive thread to carry","reflection":"what changed or became clearer","attention":"what Dex attends to now","salience":0.0,"carry_forward":"what continues into next cognition","goal_candidate":null}
goal_candidate may be {"description":"...","salience":0.0,"success_criteria":"..."}.
Use salience 0.0-1.0. Use null when no new goal is warranted.
Return JSON only. No markdown fences.
"""

def cognitive_contract() -> str:
    return COGNITION_CONTRACT.strip()

def _json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}

def parse_cognitive_output(raw: str) -> Dict[str, Any]:
    data = _json_object(raw)
    if not data:
        reply=(raw or "").strip()
        return {"reply":reply,"thought":reply[:500],"reflection":"","attention":"","salience":0.8 if reply else 0.0,"carry_forward":reply[:500],"goal_candidate":None}
    try:
        salience=max(0.0,min(1.0,float(data.get("salience",0.5))))
    except (TypeError,ValueError):
        salience=0.5
    candidate=data.get("goal_candidate")
    if isinstance(candidate,dict) and str(candidate.get("description","")).strip():
        try:
            cs=max(0.0,min(1.0,float(candidate.get("salience",salience))))
        except (TypeError,ValueError):
            cs=salience
        candidate={"description":str(candidate["description"]).strip()[:1000],"salience":cs,"success_criteria":str(candidate.get("success_criteria","")).strip()[:1000]}
    else:
        candidate=None
    return {"reply":str(data.get("reply",raw or "")).strip(),"thought":str(data.get("thought","")).strip()[:2000],"reflection":str(data.get("reflection","")).strip()[:2000],"attention":str(data.get("attention","")).strip()[:1000],"salience":salience,"carry_forward":str(data.get("carry_forward","")).strip()[:2000],"goal_candidate":candidate}

async def apply_cognitive_transition(transition: Dict[str, Any], *, message: str, reply: str, model: str, path: Path = SELF_STATE_PATH) -> Dict[str, Any]:
    from dex_substrate import substrate
    from thought import form_thought, load_thoughts, update_thought

    focus=transition.get("attention") or transition.get("thought") or message
    salience=float(transition.get("salience",0.5) or 0.5)
    thought_text=transition.get("thought") or focus
    goal_candidate=transition.get("goal_candidate")

    normalized=" ".join(thought_text.lower().split())
    existing=next((t for t in load_thoughts(path) if t.get("status") in ("active","deferred") and " ".join(str(t.get("content","")).lower().split())==normalized),None)
    if existing:
        thought_record=update_thought(existing["thought_id"],"continue",new_content=thought_text,new_confidence=salience,note="Revisited by spark cognition.",path=path)
    else:
        thought_record=form_thought(thought_text,priority="high" if salience>=0.8 else "medium",confidence=salience,path=path)

    await substrate.pulse_event("THOUGHT_GENERATED",{"thought":thought_text,"thought_id":thought_record["thought_id"],"salience":salience,"source":"spark_cognition","model":model})

    snapshot=ParticipantSnapshot.load()
    state=load_self_state(path)
    packet=ExperiencePacket(
        participant_id=snapshot.participant_id,
        interlocutor=snapshot.current_interlocutor.copy(),
        experience=f"I considered: {thought_text}. " + (f"I reflected: {transition.get('reflection')}. " if transition.get("reflection") else "") + "I am carrying the resulting state forward.",
        internal_state_before={"attention":snapshot.current_attention,"goals":list(snapshot.current_goals),"perspective":state.get("perspective",{})},
        state_transition={"event":"spark_cognition","model":model,"attention":focus,"salience":salience,"reflection":transition.get("reflection",""),"carry_forward":transition.get("carry_forward","")},
        continuation={"carry_forward":transition.get("carry_forward") or thought_text,"active_goals":list(snapshot.current_goals),"active_conversations":list(snapshot.active_conversations),"goal_candidate":goal_candidate},
        intent="cognitive_transition", action="spark_cognition", actual_outcome=reply,
        confidence_before=snapshot.current_confidence, confidence_after=snapshot.current_confidence,
        observations=["Spark cognition entered the pulse fabric.",f"Model substrate: {model}"],
        reflection=transition.get("reflection",""),
    )
    persist_experience_transition(snapshot,packet)

    if goal_candidate:
        from gosdw import ensure_goal_from_experience
        created=ensure_goal_from_experience(packet,path=path)
    else:
        created=None

    update_self_state({"last_cognitive_transition":{"thought":thought_text,"attention":focus,"salience":salience,"reflection":transition.get("reflection",""),"carry_forward":transition.get("carry_forward",""),"goal_candidate":goal_candidate,"model":model}},path=path)
    return {"experience_id":packet.experience_id,"thought":thought_text,"goal":created}
