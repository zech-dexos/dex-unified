"""Regression coverage for final ambient prompt fitting."""
import unittest
from unittest.mock import patch

import local_llm


class FakeLLM:
    def __init__(self):
        self.request = None

    def n_ctx(self):
        return 2048

    def tokenize(self, payload, add_bos=False):
        return list(payload)

    def detokenize(self, tokens):
        return bytes(tokens)

    def create_chat_completion(self, **request):
        self.request = request
        return {"choices": [{"message": {"content": '{"ok":true}'}}]}


class AmbientContextFitTests(unittest.TestCase):
    def test_final_fitted_prompt_keeps_operational_prefix_and_live_target(self):
        llm = FakeLLM()
        prompt = (
            "GOVERNING AMBIENT INSTRUCTIONS. "
            "PRIORITY OPERATIONAL SELF STATE: CURRENT_GOAL_CONTINUITY "
            "WORKSPACE=restart verification; INTENTION=preserve identity. "
            + ("HISTORICAL EXPERIENCE RECORD " * 180)
            + "SELECTED TARGET: verify restart continuity. Return ONLY JSON."
        )
        with patch.object(local_llm, "_get_llm", return_value=llm):
            result = local_llm.local_slm_generate(prompt, max_tokens=200)
        self.assertEqual(result, '{"ok":true}')
        fitted = llm.request["messages"][0]["content"]
        self.assertIn("PRIORITY OPERATIONAL SELF STATE", fitted)
        self.assertIn("CURRENT_GOAL_CONTINUITY", fitted)
        self.assertIn("SELECTED TARGET", fitted)
        self.assertLessEqual(len(llm.tokenize(fitted.encode("utf-8"))), 1752)


if __name__ == "__main__":
    unittest.main()
