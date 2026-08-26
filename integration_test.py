"""
integration_test.py — Phase 0 + 1, fully wired end to end.

Real self_state.py + real amw.py + real graph_manager.py, with only the
LLM call test-doubled (no network egress to Google available in this
sandbox, and no GEMINI_API_KEY set). Swap TestModelClient for
GeminiModelClient() in gemini_client.py and this runs identically
against the real API in your environment.
"""

from pathlib import Path
from typing import Any, Dict, List

import amw
from knowledge import graph_manager
from gemini_client import generate_reflection_text

TEST_STATE_PATH = Path("integration.self_state.test.json")
TEST_GRAPH_PATH = Path("integration.graph.test.json")


class TestModelClient:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert "TheGoldenCityOfAethel" in prompt
        return f"test_reflection #{self.calls}: synthesized understanding of the concept."


def setup():
    for p in (TEST_STATE_PATH, TEST_GRAPH_PATH):
        if p.exists():
            p.unlink()

    graph_manager.add_node("TheGoldenCityOfAethel", "entity", "A mythical city.", path=TEST_GRAPH_PATH)
    graph_manager.add_node("light_construction", "attribute", "Built of light.", path=TEST_GRAPH_PATH)
    graph_manager.add_node("fall_of_aethel", "event", "The city's fall.", path=TEST_GRAPH_PATH)
    graph_manager.add_edge("TheGoldenCityOfAethel", "light_construction", "HAS_ATTRIBUTE", weight=0.9, path=TEST_GRAPH_PATH)
    graph_manager.add_edge("light_construction", "fall_of_aethel", "PART_OF_HISTORY", weight=0.8, path=TEST_GRAPH_PATH)


def kg_lookup(concept_identifier: str) -> List[Dict[str, Any]]:
    return graph_manager.get_related_knowledge_nodes(
        concept_identifier, max_depth=2, min_relevance_score=0.7, path=TEST_GRAPH_PATH
    )


def make_llm_reflect(model_client):
    def llm_reflect(context, concept_being_held, prior_reflections=None, desired_length="medium"):
        return generate_reflection_text(
            context=context,
            concept_being_held=concept_being_held,
            prior_reflections=prior_reflections,
            desired_length=desired_length,
            model_client=model_client,
        )
    return llm_reflect


def run():
    setup()
    model_client = TestModelClient()
    llm_reflect = make_llm_reflect(model_client)

    state = amw.activate_thought(
        "TheGoldenCityOfAethel",
        "The golden city, held as an active concept.",
        duration_hint="indefinite",
        kg_lookup=kg_lookup,
        path=TEST_STATE_PATH,
    )
    nodes = state["active_mental_workspace_state"]["related_knowledge_nodes"]
    assert "light_construction" in nodes, f"expected KG traversal to find light_construction, got {nodes}"
    assert model_client.calls == 0, "activation should not call the LLM"

    for i in range(3):
        state = amw.refresh_thought(kg_lookup=kg_lookup, llm_reflect=llm_reflect, path=TEST_STATE_PATH)

    reflections = state["active_mental_workspace_state"]["internal_reflections"]
    assert len(reflections) == 3, f"expected 3 reflections after 3 refreshes, got {len(reflections)}"
    assert model_client.calls == 3
    assert "test_reflection #3" in reflections[-1]["reflection"]
    assert state["version"] == 4, f"1 activate + 3 refresh = version 4, got {state['version']}"

    report = amw.report_active_thought_state(path=TEST_STATE_PATH)
    assert "TheGoldenCityOfAethel" in report
    assert "test_reflection #3" in report

    amw.deactivate_thought(path=TEST_STATE_PATH)
    assert amw.report_active_thought_state(path=TEST_STATE_PATH) == "No active thought currently held."

    TEST_STATE_PATH.unlink()
    TEST_GRAPH_PATH.unlink()
    print("integration_test.py: all checks passed — self_state + amw + graph_manager + gemini_client wired correctly")


if __name__ == "__main__":
    run()
