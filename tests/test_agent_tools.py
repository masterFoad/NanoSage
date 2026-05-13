import tempfile
import unittest
from pathlib import Path

from agent_tools import (
    GitExploreTool,
    GrepTool,
    HeuristicAgenticPolicy,
    ReadFileLinesTool,
    ToolRequest,
    default_tool_registry,
    run_policy_tools,
)
from llm_interface import default_model_for_provider


class AgentToolsTests(unittest.TestCase):
    def test_read_file_lines_scores_and_bounds_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("alpha\nbeta architecture\ngamma\n", encoding="utf-8")
            result = ReadFileLinesTool().execute(
                root,
                ToolRequest("read_file_lines", {"path": "README.md", "start": 2, "max_lines": 1}),
                "architecture",
            )
            self.assertTrue(result.ok)
            self.assertIn("2: beta architecture", result.content)
            self.assertGreater(result.score, 0)

    def test_read_file_lines_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = ReadFileLinesTool().execute(
                root,
                ToolRequest("read_file_lines", {"path": "../secret.txt"}),
                "secret",
            )
            self.assertFalse(result.ok)

    def test_grep_finds_bounded_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def alpha(): pass\nclass Beta: pass\n", encoding="utf-8")
            result = GrepTool().execute(
                root,
                ToolRequest("grep", {"pattern": "alpha|Beta", "max_matches": 2}),
                "alpha beta",
            )
            self.assertTrue(result.ok)
            self.assertIn("a.py:1", result.content)
            self.assertIn("a.py:2", result.content)

    def test_policy_runs_registered_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("NanoSage architecture\n", encoding="utf-8")
            results, trace = run_policy_tools("NanoSage architecture", root, HeuristicAgenticPolicy(), default_tool_registry(), max_calls=2)
            self.assertEqual(len(results), 2)
            self.assertEqual(trace["calls_used"], 2)
            self.assertTrue(all(result.evidence_id.startswith("tool_") for result in results))

    def test_litellm_default_model_is_configurable_family(self):
        self.assertEqual(default_model_for_provider("litellm"), "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
