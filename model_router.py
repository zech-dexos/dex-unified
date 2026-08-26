"""
model_router.py — Talnir signal → ollama model selection
Part of the ReasonFlow / DexOS stack.

Intent overrides take priority over domain.
Add models here as they're pulled locally.
"""

# Domain-level defaults
DOMAIN_ROUTES = {
    "coding":   "qwen2.5-coder:0.5b",
    "math":     "qwen2.5:0.5b",
    "creative": "tinyllama",
    "planning": None,
    "tool":     None,
    "general":  None,
}

# Intent-level overrides (more specific — wins over domain)
INTENT_ROUTES = {
    "debug":         "qwen2.5-coder:0.5b",
    "generate_code": "qwen2.5-coder:0.5b",
    "refactor":      "qwen2.5-coder:0.5b",
    "write_tests":   "qwen2.5-coder:0.5b",
    "setup":         "qwen2.5-coder:0.5b",
    "git_operation": "qwen2.5-coder:0.5b",
    "math":          "qwen2.5:0.5b",
    "creative_write":"tinyllama",
}

DEFAULT_MODEL = "dex:latest"


def route(signal) -> str:
    """
    Given a Talnir Signal, return the ollama model name to use.
    Returns DEFAULT_MODEL if no route matches.
    """
    model = INTENT_ROUTES.get(signal.intent)
    if model:
        return model
    model = DOMAIN_ROUTES.get(signal.domain)
    if model:
        return model
    return DEFAULT_MODEL


def route_info(signal) -> dict:
    """Debug helper — returns routing decision with reason."""
    intent_model = INTENT_ROUTES.get(signal.intent)
    if intent_model:
        return {"model": intent_model, "reason": f"intent:{signal.intent}"}
    domain_model = DOMAIN_ROUTES.get(signal.domain)
    if domain_model:
        return {"model": domain_model, "reason": f"domain:{signal.domain}"}
    return {"model": DEFAULT_MODEL, "reason": "default"}
