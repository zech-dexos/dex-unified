"""Verify that local DexOS boot never imports or contacts GitHub persistence."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LocalRuntimeIsolationTests(unittest.TestCase):
    def test_local_dex_runtime_boots_without_github_connector(self):
        root = Path(__file__).resolve().parent
        script = r'''
import importlib.abc
import sys

class BlockGitHubPersistence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "github_persistence":
            raise AssertionError("local DexOS attempted to import GitHub persistence")
        return None

sys.meta_path.insert(0, BlockGitHubPersistence())
import dex_runtime
assert dex_runtime.DEXOS_ACTIVE, "local DexOS governance did not initialize"
print("local runtime booted without GitHub persistence")
'''
        with tempfile.TemporaryDirectory(prefix="dex-local-runtime-") as directory:
            env = os.environ.copy()
            env["DEX_LOCAL_RUNTIME"] = "1"
            env["DEXOS_STATE_DIR"] = directory
            env["PYTHONPATH"] = str(root)
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(root),
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"local runtime isolation failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )
        self.assertIn("local runtime booted without GitHub persistence", result.stdout)


if __name__ == "__main__":
    unittest.main()
