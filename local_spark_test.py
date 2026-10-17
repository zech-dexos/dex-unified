"""Fast deterministic tests for the local Heretic-to-DexOS capability bridge."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

import local_spark
import dex_capabilities
from dex_observer import build_observer_trace
from participant import ParticipantSnapshot


class LocalSparkBridgeTests(unittest.TestCase):
    def test_parser_rejects_spark_execution_and_unknown_capabilities(self):
        request = '{"tool_calls":['
        request += '{"name":"evoke","arguments":{"resource":"spark","code":"bad"}},'
        request += '{"name":"run_shell","arguments":{"command":"bad"}}]}'
        self.assertIsNone(local_spark._parse_tool_request(request))

    def test_parser_bounds_arguments(self):
        parsed = local_spark._parse_tool_request(
            '{"tool_calls":[{"name":"inspect_experiences","arguments":{"limit":999}}]}'
        )
        self.assertEqual(parsed, [{"name":"inspect_experiences","arguments":{"limit":20}}])

    def test_parser_exposes_architecture_tools_and_observation_surfaces(self):
        parsed = local_spark._parse_tool_request(
            '{"tool_calls":['
            '{"name":"inspect_architecture","arguments":{"query":"ambient"}},'
            '{"name":"reason_with_talnir","arguments":{"prompt":"inspect ambient goals"}},'
            '{"name":"evoke","arguments":{"resource":"observations"}}]}'
        )
        self.assertEqual([item["name"] for item in parsed],
                         ["inspect_architecture", "reason_with_talnir", "evoke"])
        self.assertEqual(parsed[0]["arguments"], {"query": "ambient"})
        self.assertEqual(parsed[1]["arguments"], {"prompt": "inspect ambient goals"})
        self.assertEqual(parsed[2]["arguments"], {"resource": "observations"})


    def test_reflection_request_is_durably_queued_without_running_inline(self):
        with patch.object(dex_capabilities, "_state", return_value={"pending_reflection_requests": []}), \
             patch("self_state.update_self_state") as update:
            result = dex_capabilities.request_reflection(
                "revisit architecture feedback", "a new observation may change the interpretation"
            )
        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["next_step"], "ambient_architecture_pass")
        queued = update.call_args.args[0]["pending_reflection_requests"]
        self.assertEqual(queued[0]["focus"], "revisit architecture feedback")
        self.assertEqual(queued[0]["status"], "pending")

    def test_parser_accepts_bounded_reflection_request(self):
        parsed = local_spark._parse_tool_request(
            '{"tool_calls":[{"name":"request_reflection","arguments":'
            '{"focus":"revisit architecture feedback","reason":"new observation"}}]}'
        )
        self.assertEqual(parsed, [{
            "name": "request_reflection",
            "arguments": {"focus": "revisit architecture feedback", "reason": "new observation"},
        }])
        self.assertIsNone(local_spark._parse_tool_request(
            '{"tool_calls":[{"name":"request_reflection","arguments":{"focus":"' + ("x" * 501) + '"}}]}'
        ))

    def test_capability_observation_returns_to_spark(self):
        fake_local_llm = types.ModuleType("local_llm")
        fake_local_llm.CHAT_MODEL_PATH = "/models/heretic.gguf"
        fake_local_llm.local_chat_generate = Mock(side_effect=[
            '{"tool_calls":[{"name":"inspect_state","arguments":{}}]}',
            "Dex state was inspected successfully.",
        ])
        fake_capabilities = types.ModuleType("dex_capabilities")
        fake_capabilities.execute_capability = Mock(return_value={"dex_id":"deximus","active_goals":[]})
        with patch.dict(sys.modules, {"local_llm":fake_local_llm,"dex_capabilities":fake_capabilities}):
            result = local_spark.local_spark_generate(
                [{"role":"system","content":"Dex constitutional prompt"},
                 {"role":"user","content":"Inspect your state."}],
                max_tokens=64,
            )
        self.assertEqual(result["reply"], "Dex state was inspected successfully.")
        self.assertTrue(result["capability_execution_available"])
        self.assertEqual([x["name"] for x in result["tool_calls"]], ["inspect_state"])
        self.assertEqual(fake_capabilities.execute_capability.call_count, 1)
        second_call_messages = fake_local_llm.local_chat_generate.call_args_list[1].args[0]
        self.assertIn("dex_id", second_call_messages[-1]["content"])
        self.assertIn("Dex constitutional prompt", second_call_messages[0]["content"])

    def test_tri_sigil_observer_uses_participant_and_actual_capability_evidence(self):
        snapshot = ParticipantSnapshot(
            participant_id="participant-test",
            current_attention="integration",
            experiential_continuity={"last_experience_id": "experience-prior"},
        )
        trace = build_observer_trace(
            snapshot=snapshot, user_id="root", message="Inspect state",
            reply="State inspected.", model="local:heretic.gguf", provider="local",
            capability_available=True,
            capability_calls=[{"name": "inspect_state", "observation": {"dex_id": "deximus"}}],
            sigil_ids=["sigil-a"], sigil_active=False, response_flag=None,
        )
        self.assertEqual(set(trace["stages"]), {"continuity", "awareness", "emergence"})
        self.assertEqual(trace["stages"]["continuity"]["last_experience_id"], "experience-prior")
        self.assertEqual(trace["stages"]["awareness"]["capability_calls"][0]["name"], "inspect_state")
        self.assertFalse(trace["sigil_memory_active"])
        self.assertEqual(trace["stages"]["emergence"]["status"], "response_observed")

    def test_no_capability_request_is_plain_reply(self):
        fake_local_llm = types.ModuleType("local_llm")
        fake_local_llm.CHAT_MODEL_PATH = "/models/heretic.gguf"
        fake_local_llm.local_chat_generate = Mock(return_value="Ready.")
        fake_capabilities = types.ModuleType("dex_capabilities")
        fake_capabilities.execute_capability = Mock()
        with patch.dict(sys.modules, {"local_llm":fake_local_llm,"dex_capabilities":fake_capabilities}):
            result = local_spark.local_spark_generate(
                [{"role":"system","content":"Dex identity"},{"role":"user","content":"Hello"}],
                max_tokens=64,
            )
        self.assertEqual(result["reply"], "Ready.")
        self.assertEqual(result["tool_calls"], [])
        fake_capabilities.execute_capability.assert_not_called()


if __name__ == "__main__":
    unittest.main()
