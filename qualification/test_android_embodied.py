import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "qualification" / "adapters" / "android_mobile_tools.py"
TASK = ROOT / "qualification" / "tasks" / "android-settings-24h-struct-v0"\nHYBRID_TASK = ROOT / "qualification" / "tasks" / "android-settings-24h-hybrid-v0"


def load_tools():
    spec = importlib.util.spec_from_file_location("android_mobile_tools_test", TOOLS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AndroidEmbodiedContractTests(unittest.TestCase):
    def test_ui_parser_exposes_only_bounded_attributes(self):
        module = load_tools()
        xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hierarchy rotation="0"><node index="0" text="Use 24-hour format" resource-id="android:id/title" class="android.widget.TextView" clickable="true" enabled="true" checked="false" scrollable="false" bounds="[10,20][210,120]" password="true" /></hierarchy>'''
        parsed = module.parse_ui_xml(xml)
        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["nodes"][0]["text"], "Use 24-hour format")
        self.assertEqual(parsed["nodes"][0]["bounds"], [10, 20, 210, 120])
        self.assertNotIn("password", parsed["nodes"][0])

    def test_task_does_not_project_verifier_truth_or_generic_shell(self):
        task = json.loads((TASK / "task.json").read_text(encoding="utf-8"))
        tools = set(task["projected_tools"])
        self.assertNotIn("run_shell", tools)
        self.assertNotIn("adb", tools)
        self.assertNotIn("mobile_open_section", tools)
        self.assertEqual(task["allowed_write_paths"], ["result.json"])

    def test_hybrid_changes_only_the_bounded_action_surface(self):
        structural = json.loads((TASK / "task.json").read_text(encoding="utf-8"))
        hybrid = json.loads((HYBRID_TASK / "task.json").read_text(encoding="utf-8"))
        structural_tools = set(structural["projected_tools"])
        hybrid_tools = set(hybrid["projected_tools"])
        self.assertEqual(
            hybrid_tools - structural_tools,
            {"mobile_open_section"},
        )
        self.assertEqual(structural["success"], hybrid["success"])
        self.assertEqual(structural["allowed_write_paths"], hybrid["allowed_write_paths"])

    def test_verifier_self_test(self):
        cp = subprocess.run([sys.executable, str(TASK / "verify.py"), "--self-test"], capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
