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

class BlockRemotePersistence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("github_persistence", "firebase_admin"):
            raise AssertionError(f"local DexOS attempted to import remote connector: {fullname}")
        return None

sys.meta_path.insert(0, BlockRemotePersistence())
import dex_runtime
assert dex_runtime.DEXOS_ACTIVE, "local DexOS governance did not initialize"
from dex_memory import _get_db
assert _get_db() is None, "local DexOS attempted to initialize Firestore"
print("local runtime booted without GitHub or Firestore")
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
        self.assertIn("local runtime booted without GitHub or Firestore", result.stdout)


if __name__ == "__main__":
    unittest.main()
