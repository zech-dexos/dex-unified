import unittest
from unittest.mock import patch

from dex_meta_dispatch import dispatch_meta_command


class MetaCommandDispatchTests(unittest.TestCase):
    @patch("dex_meta_dispatch.execute_capability")
    def test_audit_command_dispatches_only_read_only_audit(self, execute):
        execute.return_value = {"status": "clear", "read_only": True}
        result = dispatch_meta_command("!audit")
        self.assertEqual(result["status"], "clear")
        execute.assert_called_once_with("audit_cognition", {})

    @patch("dex_meta_dispatch.execute_capability")
    def test_investigation_command_passes_question(self, execute):
        execute.return_value = {"status": "planned", "question": "Why did inference fail?"}
        result = dispatch_meta_command("!investigate Why did inference fail?")
        self.assertEqual(result["status"], "planned")
        execute.assert_called_once_with(
            "build_investigation_plan",
            {"question": "Why did inference fail?"},
        )

    @patch("dex_meta_dispatch.execute_capability")
    def test_empty_or_unrecognized_commands_do_not_invoke_capabilities(self, execute):
        self.assertEqual(
            dispatch_meta_command("!investigate   "),
            {"error": "question is required", "read_only": True},
        )
        self.assertIsNone(dispatch_meta_command("please audit your cognition"))
        self.assertIsNone(dispatch_meta_command("!spark run arbitrary code"))
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
