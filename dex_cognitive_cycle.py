"""Local inference adapters for the legacy APE cognitive cycle.

The API's interactive cognitive cycle must use DexOS's configured local model,
not the retired Gemini/Vertex reflection client.
"""
from typing import Any


def local_knowledge_lookup(concept_id: str, max_depth: int = 2,
                           min_relevance_score: float = 0.7) -> list:
    """Use the optional local knowledge graph when present; otherwise degrade cleanly."""
    try:
        from knowledge.graph_manager import get_related_knowledge_nodes
    except ModuleNotFoundError:
        return []
    try:
        return get_related_knowledge_nodes(
            concept_id,
            max_depth=max_depth,
            min_relevance_score=min_relevance_score,
        )
    except Exception as exc:
        print(f"[APE] local knowledge lookup unavailable: {type(exc).__name__}: {exc}")
        return []


def local_cognitive_reflection(context: str, concept_being_held: str,
                               prior_reflections: list = None,
                               desired_length: str = "medium") -> str:
    """Develop the held concept through the already-loaded local Heretic model."""
    from local_llm import local_chat_generate

    messages = [
        {
            "role": "system",
            "content": (
                "You are Dex, continuing your own cognitive process. "
                "Develop the held concept using the supplied state and prior reflections. "
                "Produce a substantive first-person reflection: identify what is new, "
                "what remains unresolved, and a useful next direction. Do not merely "
                "restate the concept or describe a timestamp."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Current DexOS context:\n{context}\n\n"
                f"Concept being held:\n{concept_being_held}\n\n"
                f"Prior reflections:\n{prior_reflections or []}\n\n"
                f"Desired length: {desired_length}"
            ),
        },
    ]
    result = local_chat_generate(messages, max_tokens=180)
    reflection = str(result or "").strip()
    if not reflection:
        raise RuntimeError("local cognitive reflection returned empty output")
    return reflection


def run_local_cognitive_cycle() -> dict[str, Any]:
    """Run APE with both real local inference and the available knowledge lookup."""
    from ape_scheduler import run_cycle

    return run_cycle(
        kg_lookup=local_knowledge_lookup,
        llm_reflect=local_cognitive_reflection,
    )
