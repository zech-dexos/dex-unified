import sys
import types
import unittest
from unittest.mock import patch

import dex_runtime


class DexRuntimeGovernanceTests(unittest.TestCase):
    def test_unavailable_governance_holds_inference(self):
        with patch.object(dex_runtime, "_RUNTIME_INITIALIZED", True), patch.object(
            dex_runtime, "DEXOS_ACTIVE", False
        ), patch.object(dex_runtime, "_dexos", None), patch.object(
            dex_runtime, "DEXOS_INITIALIZATION_ERROR", "missing identity state"
        ):
            result = dex_runtime.dex_runtime("hello")

        self.assertTrue(result["flagged"])
        self.assertEqual(result["route_reason"], "governance_offline")
        self.assertIn("inference held", result["response"])

    def test_runtime_initializes_after_explicit_startup_call(self):
        class FakeDexOS:
            def __init__(self):
                self.initialized = False

            def initialize(self):
                self.initialized = True
                return True

        fake_module = types.ModuleType("dexos")
        fake_module.DexOS = FakeDexOS

        with patch.dict(sys.modules, {"dexos": fake_module}), patch.object(
            dex_runtime, "_RUNTIME_INITIALIZED", False
        ), patch.object(dex_runtime, "SIGIL_AVAILABLE", False), patch.object(
            dex_runtime, "_dexos", None
        ), patch.object(dex_runtime, "DEXOS_ACTIVE", False):
            self.assertTrue(dex_runtime.initialize_dex_runtime())

        # patch contexts restore module globals, so the test doesn't leak runtime state.

if __name__ == "__main__":
    unittest.main()
