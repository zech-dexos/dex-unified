"""
ReasonFlow Engine v2
Author: Zech (Root) / Deximus Maximus

Fixes from v1:
- CRITICAL: ollama called via HTTP API, not subprocess
  (was spawning new process per call → RAM explosion)
- Memory bridge: cycle trace written to dex_memory.jsonl
- Signal from Talnir translator passed through full pipeline
- context derived from signal, not duplicate keyword check
"""

import uuid
import json
import urllib.request
import urllib.error

from talnir import decompose
from .dex import select
from .memory import load_state, save_state
from .sigil import SigilMemory

try:
    from .sigil_memory_bridge import record_cycle
    BRIDGE_ACTIVE = True
except ImportError:
    BRIDGE_ACTIVE = False
    def record_cycle(*a, **k): pass

_sigil_memory = SigilMemory()

OLLAMA_URL = "http://localhost:11434/api/generate"

BRANCH_MODELS = {
    "debug_first":    "qwen2.5-coder:0.5b",
    "structured":     None,
    "direct":         None,
    "exploratory":    None,
    "planning":       None,
    "tool_execution": "qwen2.5-coder:0.5b",
}

# ─────────────────────────────────────────────
# FIXED: single HTTP call to running ollama server
# No subprocess spawn — RAM stays stable
# ─────────────────────────────────────────────

def run_model(prompt: str, model: str, config=None) -> str:
    if model is None:
        return f"[ReasonFlow:default] {prompt}"

    payload = json.dumps({
        "model": model,
        "prompt": (
            "Extract the key technical structure from this in 3 lines maximum. "
            f"Be concise. No explanation: {prompt}"
        ),
        "stream": False,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()
    except urllib.error.URLError as e:
        return f"[ollama unreachable: {e.reason}]"
    except Exception as e:
        return f"[error: {e}]"


# ─────────────────────────────────────────────
# MAIN RUN LOOP
# ─────────────────────────────────────────────

def run(prompt: str, config=None) -> dict:
    config = config or {}
    state = load_state()
    trace_id = str(uuid.uuid4())

    # TALNIR: translate NL → signal first
    graph = decompose(prompt)
    signal = graph.get("signal")

    # Context from signal (no duplicate keyword check)
    context = signal.to_context_string() if signal else "CTX:ALL"
    # Sigil system uses short context key for matching
    sigil_context = f"CTX:{signal.domain.upper()}" if signal else "CTX:ALL"

    # Activate sigils
    active_sigils = _sigil_memory.activate_for_context(sigil_context)
    resolved = _sigil_memory.resolve_conflicts(active_sigils, sigil_context)

    # Apply sigil biases to branches
    graph["branches"] = _sigil_memory.apply_to_branches(
        graph["branches"], resolved
    )

    # Select winning branch
    chosen = select(graph)

    # Route to specialized brain
    specialized_model = BRANCH_MODELS.get(chosen["id"])
    preprocessed = None

    if specialized_model:
        preprocessed = run_model(prompt, specialized_model, config)
        output = f"[preprocessed by {specialized_model}]\n{preprocessed}"
    else:
        output = f"[ReasonFlow:{chosen['id']}] {prompt}"

    trace = {
        "trace_id": trace_id,
        "input": prompt,
        "context": context,
        "signal": repr(signal) if signal else None,
        "active_sigils": [str(s) for s in resolved],
        "branches": graph["branches"],
        "selected": chosen,
        "specialized_model": specialized_model,
        "preprocessed": preprocessed,
        "output": output,
    }

    state["last"] = trace
    save_state(state)

    # Write cycle to dex_memory.jsonl
    record_cycle(trace)

    return trace
