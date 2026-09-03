import os
from pathlib import Path

# Explicit Single Source of Truth
# Railway matches /app/dexos_state. Local dev falls back to the backend folder.
_dexos_state_dir = os.environ.get("DEXOS_STATE_DIR", "").strip()
_STATE_BASE = Path(_dexos_state_dir) if _dexos_state_dir else Path("/app/dexos_state" if Path("/app").exists() else Path(__file__).parent)
_STATE_BASE.mkdir(parents=True, exist_ok=True)

IDENTITY_PATH = _STATE_BASE / "identity.json"
AMENDMENT_PATH = _STATE_BASE / "amendments.jsonl"
REFLECTION_PATH = _STATE_BASE / "reflections.jsonl"
LOOPS_PATH = _STATE_BASE / "open_loops.json"
FRAGMENTS_PATH = _STATE_BASE / "memory_seeds.jsonl"
SELF_MODEL_PATH = _STATE_BASE / "self_model.json"
COUNTERFACTUAL_PATH = _STATE_BASE / "counterfactual_archive.jsonl"
EXPERIENCES_PATH = _STATE_BASE / "experiences.jsonl"
PARTICIPANT_PATH = _STATE_BASE / "participant_state.json"
INTENTS_PATH = _STATE_BASE / "intents.json"
SESSION_PATH = _STATE_BASE / "current_session.json"
LEDGER_PATH = _STATE_BASE / "dex_lineage.jsonl"
NARRATIVE_PATH = _STATE_BASE / "narrative.jsonl"
PULSE_LOG_PATH = _STATE_BASE / "pulse.jsonl"
