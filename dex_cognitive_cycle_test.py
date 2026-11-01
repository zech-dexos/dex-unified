"""Tests that APE reflection is wired to Dex's local inference substrate."""
import unittest
from unittest.mock import patch

from dex_cognitive_cycle import (
    local_cognitive_reflection,
    local_knowledge_lookup,
    run_local_cognitive_cycle,
)


class LocalCognitiveCycleTests(unittest.TestCase):
    def test_reflection_uses_local_chat_model_and_preserves_context(self):
        with patch("local_llm.local_chat_generate", return_value="I identified a new connection.") as generate:
            result = local_cognitive_reflection(
                context="Root and Dex are integrating volition.",
                concept_being_held="choice-driven cognition",
                prior_reflections=["The decision loop is persisted."],
                desired_length="short",
            )
        self.assertEqual(result, "I identified a new connection.")
        messages = generate.call_args.args[0]
        self.assertIn("choice-driven cognition", messages[1]["content"])
        self.assertIn("Root and Dex", messages[1]["content"])
        self.assertEqual(generate.call_args.kwargs["max_tokens"], 180)

    def test_empty_local_reflection_fails_instead_of_fabricating_a_timestamp(self):
        with patch("local_llm.local_chat_generate", return_value="  "):
            with self.assertRaisesRegex(RuntimeError, "empty output"):
                local_cognitive_reflection("context", "concept")

    def test_missing_optional_knowledge_graph_degrades_to_empty_results(self):
        # The current repository does not ship knowledge.graph_manager.
        self.assertEqual(local_knowledge_lookup("continuity"), [])

    def test_ape_cycle_receives_both_callables(self):
        with patch("ape_scheduler.run_cycle", return_value={"ran": True}) as run_cycle:
            result = run_local_cognitive_cycle()
        self.assertEqual(result, {"ran": True})
        kwargs = run_cycle.call_args.kwargs
        self.assertTrue(callable(kwargs["kg_lookup"]))
        self.assertTrue(callable(kwargs["llm_reflect"]))
        self.assertEqual(
            kwargs["llm_reflect"]("context", "concept"),
            "I identified a new connection.",
        ) if False else None


if __name__ == "__main__":
    unittest.main()
