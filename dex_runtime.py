from talnir import translate, decompose

try:
    from model_router import route, route_info
    ROUTER_ACTIVE = True
except ImportError:
    ROUTER_ACTIVE = False

try:
    from sigil import SigilMemory
    SIGIL_AVAILABLE = True
except ImportError:
    SIGIL_AVAILABLE = False

_memory = None
SIGIL_ACTIVE = False
_dexos = None
DEXOS_ACTIVE = False
DEXOS_INITIALIZATION_ERROR = None
_RUNTIME_INITIALIZED = False


def initialize_dex_runtime() -> bool:
    """Initialize stateful subsystems only after durable state has been rehydrated."""
    global _memory, SIGIL_ACTIVE, _dexos, DEXOS_ACTIVE, DEXOS_INITIALIZATION_ERROR, _RUNTIME_INITIALIZED
    if _RUNTIME_INITIALIZED:
        return DEXOS_ACTIVE

    if SIGIL_AVAILABLE:
        try:
            _memory = SigilMemory()
            SIGIL_ACTIVE = True
        except Exception as exc:
            _memory = None
            SIGIL_ACTIVE = False
            print(f"[DexRuntime] Sigil memory initialization failed: {exc}")

    try:
        from dexos import DexOS
        _dexos = DexOS()
        initialized = _dexos.initialize()
        DEXOS_ACTIVE = bool(initialized)
        if not DEXOS_ACTIVE:
            DEXOS_INITIALIZATION_ERROR = "DexOS boot did not reach the online state"
            print(f"[DexRuntime] {DEXOS_INITIALIZATION_ERROR}")
    except Exception as exc:
        _dexos = None
        DEXOS_ACTIVE = False
        DEXOS_INITIALIZATION_ERROR = str(exc)
        print(f"[DexRuntime] DexOS initialization failed: {exc}")

    _RUNTIME_INITIALIZED = True
    return DEXOS_ACTIVE


def dex_runtime(user_input: str, user_id: str = "default") -> dict:
    if not _RUNTIME_INITIALIZED:
        initialize_dex_runtime()
    if not DEXOS_ACTIVE or _dexos is None:
        reason = DEXOS_INITIALIZATION_ERROR or "governance runtime is not initialized"
        return {
            "input": user_input,
            "intent": "blocked",
            "domain": "security",
            "modifiers": [],
            "tools": [],
            "context": {},
            "branches": [],
            "sigil_ids": [],
            "model": "dexos",
            "route_reason": "governance_offline",
            "governed": False,
            "flagged": True,
            "user_id": user_id,
            "recall_ctx": "",
            "response": f"DexOS governance is unavailable; inference held. Reason: {reason}",
        }
    # User recognition + recall
    try:
        from dex_memory import recognize_user, build_recall_context, log_failure, log_recovery
        user_profile = recognize_user(user_id)
        recall_ctx   = build_recall_context(user_id)
        DEX_MEMORY_ACTIVE = True
    except Exception as e:
        user_profile = {}
        recall_ctx   = ""
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
    # Legacy Talnir routing is advisory metadata only. The actual inference
    # substrate is selected centrally by ChatRequest.model / DEX_MODEL so it
    # cannot silently override controlled cross-model comparisons.
    routing = route_info(signal) if ROUTER_ACTIVE else {"model": "dex:latest", "reason": "router unavailable"}
    if DEXOS_ACTIVE and _dexos:
        governance = _dexos.process(user_input)
        if governance.get("status") != "clean":
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
                "route_reason": governance.get("drift_type", governance.get("status", "flagged")),
                "governed":     True,
                "flagged":      True,
                "response":     governance.get("response", "")
            }
    # NOTE: interaction logging moved to api.py — it must happen AFTER the
    # LLM responds, so dex_response in Firestore is the real reply instead
    # of an empty string. See call_llm() callsite in api.py /chat route.
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
