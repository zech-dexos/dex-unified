import sys
import types
import unittest
from unittest.mock import patch

import dex_ambient_daemon as ambient


class AmbientRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_model_json_is_persisted_as_parse_error(self):
        target = {"kind": "goal", "id": "goal-1", "text": "Continue the continuity audit"}

        lifecycle = types.ModuleType("dex_lifecycle")
        lifecycle.enter_active_mode = lambda state: "active"

        spark = types.ModuleType("spark_reach")
        spark.pending_spark_reaches = lambda limit=3: []

        async def invalid_json_model(prompt):
            return "this is not JSON"

        with patch.dict(sys.modules, {
            "dex_lifecycle": lifecycle,
            "spark_reach": spark,
        }), patch.object(
            ambient, "claim_ambient_tick", return_value={"due": True, "tick_count": 7}
        ), patch.object(
            ambient, "load_self_state", return_value={"persistent_thoughts": []}
        ), patch.object(
            ambient, "_select_target", return_value=target
        ), patch.object(
            ambient, "recall_into_workspace", return_value=[]
        ), patch.object(
            ambient, "format_recalled_experiences", return_value=""
        ), patch.object(ambient, "_persist_pulse_state") as persist:
            result = await ambient.run_ambient_tick(invalid_json_model)

        self.assertEqual(result["status"], "parse_error")
        persist.assert_called_once_with(target, None, 0.0, "parse_error")


if __name__ == "__main__":
    unittest.main()
