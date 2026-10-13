"""Narrow, explicit chat-command bridge for read-only cognitive meta-capabilities.

Only documented command prefixes are accepted. This deliberately does not
expose the general capability dispatcher or any state-mutating capability.
"""
from typing import Any, Dict, Optional

from dex_capabilities import execute_capability


def dispatch_meta_command(message: str) -> Optional[Dict[str, Any]]:
    """Dispatch an explicit read-only meta-command, or return None.

    Supported commands:
      !audit
      !investigate <question>
    """
    raw = str(message or "").strip()
    lowered = raw.lower()

    if lowered == "!audit":
        return execute_capability("audit_cognition", {})
    if lowered == "!investigate":
        return {"error": "question is required", "read_only": True}

    prefix = "!investigate "
    if lowered.startswith(prefix):
        question = raw[len(prefix):].strip()
        if not question:
            return {"error": "question is required", "read_only": True}
        return execute_capability(
            "build_investigation_plan",
            {"question": question},
        )

    return None
