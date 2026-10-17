"""Fast deterministic tests for the local Heretic-to-DexOS capability bridge."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

import local_spark


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
