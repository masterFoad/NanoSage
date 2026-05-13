import json
import tempfile
import unittest
from pathlib import Path

from scripts.visualize_run import render


class VisualizeRunTests(unittest.TestCase):
    def test_render_dashboard_from_tool_and_evidence_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            run = workspace / "results" / "abc123"
            run.mkdir(parents=True)
            (run / "tool_results.json").write_text(json.dumps([
                {
                    "name": "grep",
                    "args": {"pattern": "architecture"},
                    "ok": True,
                    "score": 0.75,
                    "summary": "Found architecture",
                    "content": "README.md:1 architecture",
                    "evidence_id": "tool_1",
                    "metadata": {},
                }
            ]), encoding="utf-8")
            (run / "evidence_ledger.json").write_text(json.dumps([
                {
                    "evidence_id": "ev_1",
                    "branch_query": "architecture",
                    "source_engine": "unit",
                    "url": "https://example.com",
                    "title": "Example",
                    "snippet": "snippet",
                }
            ]), encoding="utf-8")
            (run / "toc_analysis.json").write_text(json.dumps({
                "toc_tree": [{"query_text": "architecture", "relevance_score": 0.8, "metrics": {"branch_priority": 0.9, "branch_novelty": 1.0}, "children": []}],
                "analytics": {"tree_structure": {"total_nodes": 1}},
            }), encoding="utf-8")
            (run / "abc123_output.md").write_text("# Report\nArchitecture", encoding="utf-8")
            output = render(workspace, run, run / "dashboard.html")
            html = output.read_text(encoding="utf-8")
            self.assertIn("NanoSage Run Dashboard", html)
            self.assertIn("grep", html)
            self.assertIn("ev_1", html)
            self.assertIn("architecture", html)


if __name__ == "__main__":
    unittest.main()
