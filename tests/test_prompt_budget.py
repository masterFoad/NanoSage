from __future__ import annotations

import unittest

from prompt_budget import (
    EvidenceTextBlock,
    chunk_result_to_block,
    group_blocks_for_coverage,
    render_budgeted_prompt,
    select_blocks_with_budget,
)


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

    def test_coverage_groups_interleave_documents_and_span_chunk_positions(self):
        blocks = [
            EvidenceTextBlock("a", str(index), document_id="doc-a", chunk_index=index)
            for index in range(4)
        ] + [
            EvidenceTextBlock("b", str(index), document_id="doc-b", chunk_index=index)
            for index in range(4)
        ]
        groups = group_blocks_for_coverage(blocks, char_budget=8, max_groups=2)
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            [[(block.document_id, block.chunk_index) for block in group] for group in groups],
            [[("doc-a", 0), ("doc-b", 0)], [("doc-a", 3), ("doc-b", 3)]],
        )

    def test_coverage_groups_keep_chunks_whole_and_respect_call_ceiling(self):
        blocks = [
            EvidenceTextBlock("x", "A" * 5, document_id="doc", chunk_index=0),
            EvidenceTextBlock("x", "B" * 20, document_id="doc", chunk_index=1),
            EvidenceTextBlock("x", "C" * 5, document_id="doc", chunk_index=2),
        ]
        groups = group_blocks_for_coverage(blocks, char_budget=8, max_groups=1)
        self.assertEqual([[block.text for block in group] for group in groups], [["A" * 5]])
        self.assertLessEqual(sum(len(block.label) + len(block.text) + 2 for block in groups[0]), 8)


if __name__ == "__main__":
    unittest.main()
