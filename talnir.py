"""
Talnir v2 — Rule-Based Translator + Graph Decomposer
Author: Zech (Root) / Deximus Maximus

Upgrades from v1:
- translate(): NL → structured signal BEFORE routing
- decompose(): now uses translated signal, not raw prompt
- Patterns cover top coding question categories
- All existing API preserved

v2.1 fix:
- MODIFIER_CONFLICT_GROUPS: priority-based conflict resolution
- brief now correctly beats detailed on "quickly explain" etc.
"""

import re

# ─────────────────────────────────────────────
# SIGNAL SCHEMA
# A structured signal that Talnir produces before routing
# ─────────────────────────────────────────────

class Signal:
    def __init__(self, intent: str, domain: str, modifiers: list,
                 tools: list, raw: str):
        self.intent = intent        # PRIMARY: what is being asked
        self.domain = domain        # WHERE: coding / planning / tool / general
        self.modifiers = modifiers  # HOW: brief, detailed, safe, debug, etc.
        self.tools = tools          # WHAT TOOLS: search, execute, read, write
        self.raw = raw              # original input

    def to_context_string(self) -> str:
        parts = [f"CTX:{self.domain.upper()}"]
        parts += [f"MOD:{m}" for m in self.modifiers]
        parts += [f"TOOL:{t}" for t in self.tools]
        return " ".join(parts)

    def __repr__(self):
        return (f"Signal(intent={self.intent!r}, domain={self.domain!r}, "
                f"modifiers={self.modifiers}, tools={self.tools})")


# ─────────────────────────────────────────────
# PATTERN TABLE
# Top coding + reasoning patterns → structured signal
# ─────────────────────────────────────────────

INTENT_PATTERNS = [
    # CODING — debug / fix
    (r"\b(debug|fix|broken|crash|error|traceback|exception|not working)\b",
     "debug", "coding", ["debug_mode"]),

    # CODING — write / generate
    (r"\b(write|create|generate|make|build)\b.{0,30}\b(function|class|script|module|code|program)\b",
     "generate_code", "coding", ["output_code"]),

    # CODING — explain code
    (r"\b(explain|what does|how does|walk me through)\b.{0,30}\b(code|function|script|this)\b",
     "explain_code", "coding", ["detailed"]),

    # CODING — refactor / improve
    (r"\b(refactor|improve|optimize|clean up|rewrite)\b",
     "refactor", "coding", ["structured"]),

    # CODING — test
    (r"\b(test|unit test|pytest|assert|mock|coverage)\b",
     "write_tests", "coding", ["output_code"]),

    # CODING — install / setup
    (r"\b(install|setup|configure|pip|npm|apt|brew|requirements)\b",
     "setup", "coding", ["step_by_step"]),

    # CODING — git
    (r"\b(git|commit|push|pull|branch|merge|rebase|clone)\b",
     "git_operation", "coding", ["tool_use"]),

    # CREATIVE — must be before file_operation to prevent "write" collision
    (r"\b(write|create|generate)\b.{0,30}\b(story|poem|fiction|narrative|character|dialogue|creative)\b",
     "creative_write", "creative", ["exploratory"]),

    # CREATIVE
    (r"\b(write|create|generate)\b.{0,30}\b(story|poem|fiction|narrative|character|dialogue|creative)\b",
     "creative_write", "creative", ["exploratory"]),

    # TOOL — execute command

    (r"\b(run|execute|launch|start|stop|restart|kill|process)\b",
     "execute", "tool", ["tool_use"]),

    # TOOL — search
    (r"\b(search|find|look up|google|fetch|retrieve)\b",
     "search", "tool", ["tool_use", "search"]),

    # TOOL — read/write file
    (r"\b(read|open|load|write|save|edit|file|directory|path)\b",
     "file_operation", "tool", ["tool_use"]),

    # PLANNING — architect
    (r"\b(design|architect|plan|structure|layout|how should i)\b",
     "plan", "planning", ["structured", "detailed"]),

    # PLANNING — roadmap
    (r"\b(roadmap|steps|what do i need|how do i approach|where do i start)\b",
     "roadmap", "planning", ["step_by_step"]),


    # MATH
    (r"\b(calculate|compute|solve|equation|algebra|calculus|derivative|integral|probability|statistics|matrix)\b",
     "math", "math", ["structured"]),

    # BRIEF request — modifier only, no intent override
    (r"\b(quick|quickly|briefly|brief|short|summary|tldr|in one line|just tell me)\b",
     None, None, ["brief"]),

    # REASONING — explain concept
    (r"\b(what is|explain|how does|why does|tell me about)\b",
     "explain", "general", ["detailed"]),

    # REASONING — compare
    (r"\b(compare|difference between|vs|versus|which is better)\b",
     "compare", "general", ["structured"]),

    # SAFE / CHECK
    (r"\b(safe|secure|check|validate|verify|audit)\b",
     None, None, ["safety_check"]),
]


# ─────────────────────────────────────────────
# MODIFIER CONFLICT RESOLUTION
# When two modifiers in the same group both fire, highest priority wins.
# Priority = position in list (index 0 beats index 1 beats index 2).
# Add new conflict groups here as needed.
# ─────────────────────────────────────────────

MODIFIER_CONFLICT_GROUPS = [
    ["brief", "detailed", "step_by_step"],  # verbosity — brief wins
]


# ─────────────────────────────────────────────
# TRANSLATOR
# ─────────────────────────────────────────────

def translate(prompt: str) -> Signal:
    """
    Rule-based translator: NL → structured Signal.
    Called BEFORE decompose() and routing.
    """
    p = prompt.lower()

    intent = "general"
    domain = "general"
    modifiers = []
    tools = []

    for pattern, p_intent, p_domain, p_modifiers in INTENT_PATTERNS:
        if re.search(pattern, p):
            if p_intent and intent == "general":
                intent = p_intent
            if p_domain and domain == "general":
                domain = p_domain
            for mod in p_modifiers:
                if mod.startswith("tool_use") or mod == "search":
                    if mod not in tools:
                        tools.append(mod)
                else:
                    if mod not in modifiers:
                        modifiers.append(mod)

    # Conflict resolution: for each group, keep only the highest-priority modifier
    for group in MODIFIER_CONFLICT_GROUPS:
        hits = [m for m in group if m in modifiers]
        if len(hits) > 1:
            winner = hits[0]  # first in group = highest priority
            for loser in hits[1:]:
                modifiers.remove(loser)

    # Default modifier if nothing matched
    if not modifiers:
        modifiers = ["normal"]

    return Signal(
        intent=intent,
        domain=domain,
        modifiers=modifiers,
        tools=tools,
        raw=prompt,
    )


# ─────────────────────────────────────────────
# DECOMPOSER — v2: uses Signal, not raw prompt
# ─────────────────────────────────────────────

def decompose(prompt: str) -> dict:
    """
    v2: translate first, then build branches from signal.
    Preserves original return shape — engine.py unchanged.
    """
    signal = translate(prompt)
    p = prompt.lower()

    branches = [
        {"id": "direct",      "weight": 0.7},
        {"id": "structured",  "weight": 0.6},
        {"id": "exploratory", "weight": 0.5},
    ]

    # Route by intent (translated signal — more precise than raw keywords)
    if signal.intent in ("debug", "refactor"):
        branches.append({"id": "debug_first", "weight": 0.90})

    if signal.intent in ("plan", "roadmap"):
        branches.append({"id": "planning", "weight": 0.88})

    if signal.intent in ("execute", "search", "file_operation", "git_operation"):
        branches.append({"id": "tool_execution", "weight": 0.88})

    if signal.intent in ("generate_code", "write_tests"):
        branches.append({"id": "debug_first", "weight": 0.85})

    # Modifier influence
    if "brief" in signal.modifiers:
        branches = [{**b, "weight": b["weight"] * 0.8} for b in branches]
        branches = [{**b, "weight": min(1.0, b["weight"] + 0.15)
                     if b["id"] == "direct" else b["weight"]} for b in branches]

    if "detailed" in signal.modifiers:
        branches = [{**b, "weight": min(1.0, b["weight"] + 0.1)
                     if b["id"] in ("structured", "exploratory") else b["weight"]}
                    for b in branches]

    return {
        "branches": branches,
        "signal": signal,
        "context": signal.to_context_string(),
    }
