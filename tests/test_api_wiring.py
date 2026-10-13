import ast
import unittest
from pathlib import Path


API_PATH = Path(__file__).resolve().parents[1] / "api.py"
API_SOURCE = API_PATH.read_text(encoding="utf-8")
API_TREE = ast.parse(API_SOURCE)


def _function(name):
    return next(
        node for node in API_TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _awaits_call(function, call_name):
    return any(
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == call_name
        for node in ast.walk(function)
    )


class ApiWiringTests(unittest.TestCase):
    def test_legacy_pulse_awaits_the_async_background_cycle(self):
        self.assertTrue(_awaits_call(_function("trigger_pulse"), "run_background_pulse"))

    def test_ambient_endpoint_awaits_one_cognition_tick(self):
        self.assertTrue(_awaits_call(_function("trigger_ambient_pulse"), "run_ambient_tick"))
        self.assertTrue(_awaits_call(_function("trigger_ambient_pulse"), "_persist_github_state"))

    def test_pulse_failures_are_reported_as_http_errors(self):
        for name in ("trigger_pulse", "trigger_ambient_pulse"):
            source = ast.get_source_segment(API_SOURCE, _function(name))
            self.assertIn("raise HTTPException(status_code=500", source)

    def test_both_pulse_routes_require_governance(self):
        for name in ("trigger_pulse", "trigger_ambient_pulse"):
            function = _function(name)
            calls = {
                node.func.id for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            self.assertIn("_governance_status", calls)

    def test_startup_rehydrates_before_runtime_and_subscribers(self):
        function = _function("start_continuous_substrate")
        def call_line(name):
            return min(
                node.lineno for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == name
            )

        self.assertLess(call_line("pull_from_github"), call_line("initialize_dex_runtime"))
        self.assertLess(call_line("initialize_dex_runtime"), call_line("setup_continuity"))


if __name__ == "__main__":
    unittest.main()
