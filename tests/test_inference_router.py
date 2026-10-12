import os
import unittest
from unittest.mock import AsyncMock, patch

import inference_router


class ModelSpecTests(unittest.TestCase):
    def test_openrouter_free_suffix_is_preserved(self):
        self.assertEqual(
            inference_router._parse_model_spec(
                "openrouter:google/gemma-4-26b-a4b-it:free"
            ),
            ("openrouter", "google/gemma-4-26b-a4b-it:free"),
        )

    def test_legacy_gemini_name_maps_to_vertex(self):
        self.assertEqual(
            inference_router._parse_model_spec("gemini-2.0-flash"),
            ("vertex", "gemini-2.0-flash"),
        )

    def test_explicit_provider_prefix_is_respected(self):
        self.assertEqual(
            inference_router._parse_model_spec("groq:openai/gpt-oss-20b"),
            ("groq", "openai/gpt-oss-20b"),
        )

    def test_ollama_provider_is_supported(self):
        self.assertEqual(
            inference_router._parse_model_spec("ollama:qwen3:8b"),
            ("ollama", "qwen3:8b"),
        )

    def test_openai_compatible_base_url_normalization(self):
        self.assertEqual(
            inference_router._chat_completions_url("http://gpu.example/v1/"),
            "http://gpu.example/v1/chat/completions",
        )
        self.assertEqual(
            inference_router._chat_completions_url("http://gpu.example/v1/chat/completions"),
            "http://gpu.example/v1/chat/completions",
        )


class ModelFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_strict_explicit_selection_does_not_fallback(self):
        with patch.object(
            inference_router, "_call_selected_model", new=AsyncMock(return_value=None)
        ) as selected:
            result = await inference_router.call_llm(
                object(),
                [{"role": "user", "content": "test"}],
                requested_model="openrouter:provider/model",
                allow_fallback=False,
            )

        self.assertEqual(result["model"], "none")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(selected.await_count, 1)

    async def test_implicit_selection_uses_and_reports_fallback(self):
        original = os.environ.get("DEX_FALLBACK_MODELS")
        os.environ["DEX_FALLBACK_MODELS"] = "openrouter:provider/backup"

        async def fake_selected(client, messages, model_spec, max_tokens, enable_tools=True):
            if model_spec == "openrouter:provider/backup":
                return {
                    "reply": "backup response",
                    "model": "provider/backup",
                    "provider": "openrouter",
                    "requested_model": model_spec,
                }
            return None

        try:
            with patch.object(
                inference_router, "_call_selected_model", side_effect=fake_selected
            ):
                result = await inference_router.call_llm(
                    object(), [{"role": "user", "content": "test"}]
                )
        finally:
            if original is None:
                os.environ.pop("DEX_FALLBACK_MODELS", None)
            else:
                os.environ["DEX_FALLBACK_MODELS"] = original

        self.assertEqual(result["model"], "provider/backup")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["requested_model"], inference_router.DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
