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
    async def test_rate_limit_cooldown_is_recorded_and_respected(self):
        inference_router._MODEL_COOLDOWNS.clear()
        inference_router._record_provider_failure(
            "openrouter", "provider/model", 429, "rate limit reached", "30"
        )
        self.assertTrue(inference_router._model_is_cooling_down("openrouter", "provider/model"))
        self.assertFalse(inference_router._model_is_cooling_down("openrouter", "provider/other"))
        inference_router._MODEL_COOLDOWNS.clear()

    async def test_shared_cooldown_survives_local_cache_reset(self):
        import dex_memory

        store = {}

        class Snapshot:
            def __init__(self, data):
                self.data = data

            def to_dict(self):
                return dict(self.data)

        class Document:
            def __init__(self, key):
                self.key = key

            def get(self):
                return Snapshot(store.get(self.key, {}))

            def set(self, data, merge=False):
                if merge:
                    store.setdefault(self.key, {}).update(data)
                else:
                    store[self.key] = dict(data)

        class Collection:
            def document(self, key):
                return Document(key)

        class FakeDb:
            def collection(self, name):
                return Collection()

        inference_router._MODEL_COOLDOWNS.clear()
        inference_router._SHARED_COOLDOWN_CACHE.clear()
        with patch.object(dex_memory, "_get_db", return_value=FakeDb()):
            inference_router._persist_shared_cooldown(
                "provider:openrouter", "openrouter", "model", 60, "quota"
            )
            inference_router._MODEL_COOLDOWNS.clear()
            inference_router._SHARED_COOLDOWN_CACHE.clear()
            self.assertGreater(
                inference_router._cooldown_remaining("provider:openrouter"), 0
            )
        inference_router._MODEL_COOLDOWNS.clear()
        inference_router._SHARED_COOLDOWN_CACHE.clear()

    async def test_daily_quota_cools_down_entire_provider(self):
        inference_router._MODEL_COOLDOWNS.clear()
        inference_router._record_provider_failure(
            "groq", "openai/gpt-oss-20b", 429, "TPD quota exceeded"
        )
        self.assertTrue(inference_router._model_is_cooling_down("groq", "openai/other-model"))
        inference_router._MODEL_COOLDOWNS.clear()

    async def test_local_adapter_runs_without_api_client_or_tools(self):
        import sys
        from types import SimpleNamespace

        fake_local = SimpleNamespace(
            local_slm_generate=lambda prompt, max_tokens: "local answer",
            MODEL_PATH="/tmp/test-model.gguf",
        )
        with patch.dict(sys.modules, {"local_llm": fake_local}):
            result = await inference_router._call_selected_model(
                None,
                [{"role": "user", "content": "test prompt"}],
                "local:default",
                80,
                enable_tools=False,
            )

        self.assertEqual(result["reply"], "local answer")
        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["model"], "test-model.gguf")
        self.assertFalse(result["capability_execution_available"])

    async def test_invalid_model_spec_returns_failure_instead_of_raising(self):
        result = await inference_router.call_llm(
            object(),
            [{"role": "user", "content": "test"}],
            requested_model="vertex:",
            allow_fallback=False,
        )
        self.assertEqual(result["provider"], "none")
        self.assertFalse(result["fallback_used"])

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
