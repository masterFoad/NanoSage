import tempfile
import unittest
from pathlib import Path

from agent_tools import HeuristicAgenticPolicy, run_policy_tools


class IterativeAgentPolicyTests(unittest.TestCase):
    def test_iterative_policy_follows_grep_hits_with_read_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("NanoSage architecture\n", encoding="utf-8")
            (root / "search_session.py").write_text("class SearchSession:\n    pass\n# architecture hook\n", encoding="utf-8")
            results, trace = run_policy_tools(
                "SearchSession architecture",
                root,
                HeuristicAgenticPolicy(),
                max_rounds=3,
                max_calls=8,
            )
            self.assertGreaterEqual(len(trace["rounds"]), 2)
            self.assertTrue(any(r.name == "grep" for r in results))
            self.assertTrue(any(r.name == "read_file_lines" and r.args.get("path") == "search_session.py" for r in results))
            self.assertIn(trace["stop_reason"], {"no_new_requests", "max_calls_reached", "max_rounds_reached"})

    def test_policy_respects_max_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("architecture\n", encoding="utf-8")
            results, trace = run_policy_tools(
                "architecture",
                root,
                HeuristicAgenticPolicy(),
                max_rounds=5,
                max_calls=2,
            )
            self.assertLessEqual(len(results), 2)
            self.assertEqual(trace["calls_used"], len(results))


if __name__ == "__main__":
    unittest.main()
