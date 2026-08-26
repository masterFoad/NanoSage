from __future__ import annotations

import unittest

from chunking import collapse_whitespace, normalize_extracted_text, split_text_into_chunks
from prompt_budget import EvidenceTextBlock, select_blocks_with_budget


class ChunkingTests(unittest.TestCase):
    def test_normalize_collapses_horizontal_whitespace_but_keeps_structure(self):
        self.assertEqual(normalize_extracted_text("  alpha\n\n beta\tgamma  "), "alpha\n\nbeta gamma")
        self.assertEqual(normalize_extracted_text("a  \n  b"), "a\nb")

    def test_normalize_caps_blank_line_runs_and_is_idempotent(self):
        once = normalize_extracted_text("alpha\n\n\n\n\nbeta")
        self.assertEqual(once, "alpha\n\nbeta")
        self.assertEqual(normalize_extracted_text(once), once)

    def test_normalize_handles_crlf_and_empty(self):
        self.assertEqual(normalize_extracted_text("alpha\r\n\r\nbeta"), "alpha\n\nbeta")
        self.assertEqual(normalize_extracted_text(""), "")

    def test_collapse_whitespace_is_structure_insensitive(self):
        self.assertEqual(collapse_whitespace("alpha\n\nbeta  gamma"), "alpha beta gamma")
        self.assertEqual(collapse_whitespace("  alpha\tbeta  "), "alpha beta")

    def test_chunker_splits_on_preserved_paragraph_boundary(self):
        text = normalize_extracted_text("Alpha one paragraph here.\n\nBeta second paragraph here.")
        chunks = split_text_into_chunks("ev", text, chunk_chars=34, chunk_overlap=4)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(chunks[0].text.endswith("."))
        for chunk in chunks:
            self.assertEqual(text[chunk.char_start:chunk.char_end], chunk.text)

    def test_chunks_have_offsets_into_supplied_text(self):
        text = normalize_extracted_text("Alpha beta gamma. Delta epsilon zeta. Eta theta iota.")
        chunks = split_text_into_chunks(
            "ev_1",
            text,
            chunk_chars=28,
            chunk_overlap=8,
            max_chunks_per_doc=4,
        )
        self.assertGreaterEqual(len(chunks), 2)
        for chunk in chunks:
            self.assertEqual(text[chunk.char_start:chunk.char_end], chunk.text)
            self.assertTrue(chunk.text)
        self.assertEqual(len({(c.char_start, c.char_end) for c in chunks}), len(chunks))

    def test_max_chunks_bounds_output(self):
        chunks = split_text_into_chunks(
            "ev_1",
            " ".join(str(i) for i in range(100)),
            chunk_chars=20,
            chunk_overlap=5,
            max_chunks_per_doc=3,
        )
        self.assertEqual(len(chunks), 3)

    def test_empty_and_short_text(self):
        self.assertEqual(split_text_into_chunks("ev", ""), [])
        chunks = split_text_into_chunks("ev", "short text", chunk_chars=20, chunk_overlap=5)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "short text")

    def test_prefers_sentence_boundary_near_target(self):
        text = "Alpha one. Beta two continues farther. Gamma three."
        chunks = split_text_into_chunks("ev", text, chunk_chars=18, chunk_overlap=4)
        self.assertTrue(chunks[0].text.endswith("."))

    def test_hard_splits_when_no_boundary_exists(self):
        text = "x" * 45
        chunks = split_text_into_chunks("ev", text, chunk_chars=20, chunk_overlap=5)
        self.assertEqual(chunks[0].char_end, 20)
        self.assertLess(chunks[1].char_start, chunks[0].char_end)

    def test_budget_keeps_whole_ranked_segments(self):
        blocks = [EvidenceTextBlock("a", "aaaa", 2.0), EvidenceTextBlock("b", "bbbb", 1.0)]
        self.assertEqual([block.text for block in select_blocks_with_budget(blocks, 14)], ["aaaa", "bbbb"])
        self.assertEqual(select_blocks_with_budget([EvidenceTextBlock("x", "toolong", 1.0)], 3), [])


if __name__ == "__main__":
    unittest.main()
