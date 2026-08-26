from __future__ import annotations

import unittest

from prompt_budget import EvidenceTextBlock, chunk_result_to_block, render_budgeted_prompt, select_blocks_with_budget


class PromptBudgetTests(unittest.TestCase):
    def test_drops_lowest_scoring_whole_blocks(self):
        blocks = [
            EvidenceTextBlock("low", "L" * 10, 0.1),
            EvidenceTextBlock("high", "H" * 10, 0.9),
        ]
        selected = select_blocks_with_budget(blocks, len("high") + 10 + 2)
        self.assertEqual([block.label for block in selected], ["high"])

    def test_stable_prefix_precedes_variable_evidence(self):
        prompt, selected = render_budgeted_prompt(
            "STABLE INSTRUCTIONS",
            [EvidenceTextBlock("Evidence", "variable", 1.0)],
            100,
            evidence_heading="VARIABLE EVIDENCE",
            suffix="REPORT",
        )
        self.assertEqual(len(selected), 1)
        self.assertLess(prompt.index("STABLE INSTRUCTIONS"), prompt.index("variable"))
        self.assertTrue(prompt.endswith("REPORT"))

    def test_chunk_block_uses_retrieved_text_not_preview(self):
        block = chunk_result_to_block({
            "metadata": {
                "parent_evidence_id": "ev_1",
                "url": "https://example.test",
                "char_start": 10,
                "char_end": 20,
                "text": "retrieved chunk",
                "text_preview": "crawler preview",
                "search_score": 0.8,
            }
        })
        self.assertEqual(block.text, "retrieved chunk")
        self.assertNotIn("crawler preview", block.text)
        self.assertIn("ev_1", block.label)
        self.assertIn("10-20", block.label)


if __name__ == "__main__":
    unittest.main()
