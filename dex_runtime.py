import os

from talnir import translate, decompose
try:
    from model_router import route, route_info
    ROUTER_ACTIVE = True
except ImportError:
    ROUTER_ACTIVE = False
try:
    from sigil import SigilMemory
    _memory = SigilMemory()
    SIGIL_ACTIVE = True
except ImportError:
    SIGIL_ACTIVE = False
    _memory = None
try:
    from pathlib import Path
    Path("/app/dexos_state").mkdir(exist_ok=True)
    from github_persistence import pull_from_github, push_to_github
    pull_from_github()
    from dexos import DexOS
    _dexos = DexOS()
    _dexos.initialize()
    DEXOS_ACTIVE = True
except Exception as e:
    DEXOS_ACTIVE = False
    _dexos = None


def dex_runtime(user_input: str, user_id: str = "default") -> dict:
    # Local workstation cognition must use DexOS's local continuity records.
    # Firestore is a separate Haven/cloud integration, not a prerequisite for
    # a local chat turn. A synchronous Firestore stream here can hold the
    # async /chat handler before inference even begins.
    if os.environ.get("DEX_LOCAL_RUNTIME") == "1":
        try:
            from dex_conversation import load_conversation, format_conversation_context

            user_profile = {"user_id": user_id, "memory_backend": "local"}
            recall_ctx = format_conversation_context(load_conversation(user_id))
            DEX_MEMORY_ACTIVE = True
            print("[dex_runtime] local-first memory active; Firestore bypassed", flush=True)
        except Exception as e:
            user_profile = {"user_id": user_id, "memory_backend": "local"}
            recall_ctx = ""
            DEX_MEMORY_ACTIVE = False
            print(f"[dex_runtime] local continuity recall unavailable: {e}", flush=True)
    else:
        # Hosted deployments retain their existing Firestore-backed profile
        # and recall behavior.
        try:
            from dex_memory import recognize_user, build_recall_context, log_failure
            user_profile = recognize_user(user_id)
            recall_ctx = build_recall_context(user_id)
            DEX_MEMORY_ACTIVE = True
        except Exception as e:
            user_profile = {}
            recall_ctx = ""
            DEX_MEMORY_ACTIVE = False
            try:
                from dex_memory import log_failure
                log_failure("dex_memory", str(e), recovered=True)
            except Exception:
                pass

    result = decompose(user_input)
    signal = result["signal"]
    sigil_ids = []
    if SIGIL_ACTIVE and _memory:
        context = signal.domain or "CTX:ALL"
        active = _memory.activate_for_context(context)
        active = _memory.resolve_conflicts(active, context)
        sigil_ids = [s.id for s in active]
        # Apply learned Sigil bias to the branches used by Dex's active runtime.
        # Preserve Talnir's original branches if the optional weighting step fails.
        try:
            result["branches"] = _memory.apply_to_branches(
                result["branches"], active
            )
        except Exception as e:
            print(f"[sigil] branch weighting skipped: {e}")
    routing = route_info(signal) if ROUTER_ACTIVE else {"model": "dex:latest", "reason": "router unavailable"}
    if DEXOS_ACTIVE and _dexos:
        governance = _dexos.process(user_input)
        if governance.get("status") == "flagged":
            return {
                "input":        user_input,
                "intent":       "blocked",
                "domain":       "security",
                "modifiers":    [],
                "tools":        [],
                "context":      {},
                "branches":     [],
                "sigil_ids":    [],
                "model":        "dexos",
                "route_reason": governance.get("drift_type", "flagged"),
                "governed":     True,
                "flagged":      True,
                "response":     governance.get("response", "")
            }
    # NOTE: interaction logging moved to api.py — it must happen AFTER the
    # LLM responds. Local turns are recorded by DexOS's local experience and
    # conversation stores; hosted turns retain the Firestore-backed path.
    return {
        "input":        user_input,
        "intent":       signal.intent,
        "domain":       signal.domain,
        "modifiers":    signal.modifiers,
        "tools":        signal.tools,
        "context":      result["context"],
        "branches":     result["branches"],
        "sigil_ids":    sigil_ids,
        "model":        routing["model"],
        "route_reason": routing["reason"],
        "governed":     DEXOS_ACTIVE,
        "flagged":      False,
        "user_id":      user_id,
        "recall_ctx":   recall_ctx,
    }
