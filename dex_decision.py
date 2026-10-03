"""dex_decision.py — conversational decision authority for DexOS.

The spark may express a deliberate state decision during an active
conversation, but only DexOS applies the decision to persistent state.
Exactly one decision marker is accepted per response.
"""

import json
import re
from typing import Any, Dict, Optional, Tuple

from gosdw import update_goal_status
from thought import update_thought

_DECISION_RE = re.compile(
    r"<DEX_STATE_DECISION>\s*(\{.*?\})\s*</DEX_STATE_DECISION>",
    re.DOTALL,
)

VALID_THOUGHT_DECISIONS = {"continue", "resolve", "defer", "abandon"}
VALID_GOAL_STATUSES = {"active", "paused", "completed", "failed"}


def apply_conversational_decision(reply: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Apply one explicit conversational state decision and strip its marker."""
    if not isinstance(reply, str):
        return reply, None

    match = _DECISION_RE.search(reply)
    if not match:
        return reply, None

    clean_reply = (reply[:match.start()] + reply[match.end():]).strip()
    try:
        decision = json.loads(match.group(1))
    except json.JSONDecodeError:
        return reply, {
            "applied": False,
            "reason": "invalid_decision_json",
        }

    target_type = str(decision.get("target_type", "")).strip().lower()
    target_id = str(decision.get("target_id", "")).strip()
    action = str(decision.get("decision", "")).strip().lower()
    reason = str(decision.get("reason", "")).strip()
    if not target_type or not target_id or not action:
        return clean_reply, {
            "applied": False,
            "reason": "missing_decision_fields",
        }

    if target_type == "thought":
        if action not in VALID_THOUGHT_DECISIONS:
            return clean_reply, {
                "applied": False,
                "reason": "invalid_thought_decision",
                "decision": action,
                "target_id": target_id,
            }

        updated = update_thought(
            target_id,
            decision=action,
            new_content=decision.get("new_content"),
            new_confidence=decision.get("new_confidence"),
            note=reason or "Conversational cognition applied a deliberate state decision.",
            next_attention_at=decision.get("next_attention_at"),
        )
        return clean_reply, {
            "applied": updated is not None,
            "target_type": "thought",
            "target_id": target_id,
            "action": action,
            "status": updated.get("status") if updated else None,
        }

    if target_type == "goal":
        if action not in VALID_GOAL_STATUSES:
            return clean_reply, {
                "applied": False,
                "reason": "invalid_goal_status",
                "decision": action,
                "target_id": target_id,
            }

        updated = update_goal_status(
            target_id,
            action,
            progress_report=reason or None,
        )
        return clean_reply, {
            "applied": updated is not None,
            "target_type": "goal",
            "target_id": target_id,
            "action": action,
            "status": updated.get("status") if updated else None,
        }

    return clean_reply, {
        "applied": False,
        "reason": "unsupported_target_type",
        "target_type": target_type,
        "target_id": target_id,
    }
