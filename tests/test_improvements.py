"""Tests for the evidence-quality and failure-handling changes."""

from __future__ import annotations

import unittest

from evidence import blend_relevance, numbers_supported_by_quote, verify_claims
from llm_interface import _summary_prompt


class BlendRelevanceTests(unittest.TestCase):
    def test_no_parent_returns_root_score(self):
        self.assertEqual(blend_relevance(0.42, None, 0.4), 0.42)

    def test_zero_weight_ignores_parent(self):
        self.assertEqual(blend_relevance(0.42, 0.99, 0.0), 0.42)

    def test_child_close_to_parent_outscores_root_only(self):
        # The concrete regression: a KV-cache-formula sub-question scores 0.356
        # against the root query but is squarely on-topic for its parent branch.
        root_only = blend_relevance(0.356, 0.82, 0.0)
        blended = blend_relevance(0.356, 0.82, 0.4)
        self.assertGreater(blended, root_only)
        self.assertAlmostEqual(blended, (0.6 * 0.356) + (0.4 * 0.82))

    def test_rejects_weight_out_of_range(self):
        with self.assertRaises(ValueError):
            blend_relevance(0.5, 0.5, 1.5)


class NumericSupportTests(unittest.TestCase):
    def test_accepts_claim_whose_numbers_are_in_the_quote(self):
        self.assertTrue(numbers_supported_by_quote(
            "A 35B-A3B model activates about 3 billion parameters per token",
            "a model labelled 35B-A3B has 35 billion total parameters but only about 3 billion active per token.",
        ))

    def test_accepts_claim_with_no_numbers(self):
        self.assertTrue(numbers_supported_by_quote("MoE keeps compute low", "MoE keeps compute low"))

    def test_rejects_a_number_the_quote_never_states(self):
        self.assertFalse(numbers_supported_by_quote(
            "MoE inference is 3x faster than dense",
            "MoE inference can be faster than dense in some configurations",
        ))

    def test_thousands_separator_matches(self):
        self.assertTrue(numbers_supported_by_quote("uses 1024 experts", "uses 1,024 experts"))

    def test_model_names_are_identifiers_not_quantities(self):
        # A real false positive: "OLMoE-1B-7B" was read as claiming 1 and 7, so a
        # faithful claim was rejected against a quote saying the same thing.
        self.assertTrue(numbers_supported_by_quote(
            "OLMoE-1B-7B runs 31% behind with 2.1x the energy per token and peak memory at the 8 GB ceiling",
            "and erodes on the edge device (31 % behind, at 2.1 the energy per token, with peak memory at the 8 GB ceiling).",
        ))

    def test_quantities_leading_a_word_still_count(self):
        self.assertFalse(numbers_supported_by_quote("a 70B model needs 140 GB", "a 70B model"))
        self.assertTrue(numbers_supported_by_quote("a 70B model", "a 70B dense model touches all weights"))

    def test_punctuation_around_a_quantity_is_ignored(self):
        self.assertTrue(numbers_supported_by_quote("roughly (31%) slower", "about 31 % slower"))

    def test_markdown_emphasis_around_a_quantity_is_ignored(self):
        # Extracted page text keeps markdown, so the quote carried "**3 billion
        # active**" while the claim said "3 billion" -- a false rejection.
        self.assertTrue(numbers_supported_by_quote(
            "has 35 billion total parameters but only about 3 billion active per token",
            "has 35 billion total parameters but only about **3 billion active** per token.",
        ))
        self.assertTrue(numbers_supported_by_quote("reaches 30 tokens/s", "reaches `30` tokens/s"))


class VerifyClaimsNumericGateTests(unittest.TestCase):
    def test_verbatim_quote_with_invented_number_is_rejected(self):
        text = "MoE inference can be faster than dense in some configurations."
        claims = [{
            "claim_text": "MoE inference is 3x faster than dense",
            "evidence_id": "ev_1",
            "quote": "MoE inference can be faster than dense",
        }]
        kept, rejected = verify_claims(claims, {"ev_1": text})
        # The quote IS present verbatim, so span verification alone would keep it.
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["rejection_reason"], "numbers_not_in_quote")

    def test_supported_claim_still_keeps_derived_offsets(self):
        text = "Prefix. A 70B dense model touches all 70 billion parameters. Suffix."
        claims = [{
            "claim_text": "A 70B dense model touches all 70 billion parameters",
            "evidence_id": "ev_1",
            "quote": "A 70B dense model touches all 70 billion parameters",
        }]
        kept, rejected = verify_claims(claims, {"ev_1": text})
        self.assertEqual(rejected, [])
        self.assertEqual(text[kept[0]["claim"]["char_start"]:kept[0]["claim"]["char_end"]], claims[0]["quote"])


class SummaryPromptTests(unittest.TestCase):
    def test_without_question_keeps_the_generic_prompt(self):
        prompt = _summary_prompt("BODY")
        self.assertIn("summarize the following text", prompt)
        self.assertIn("BODY", prompt)

    def test_with_question_directs_the_summary(self):
        prompt = _summary_prompt("BODY", "At what context length does the KV cache exceed 16 GB?")
        self.assertIn("Research question: At what context length", prompt)
        self.assertIn("as an answer to that question", prompt)
        self.assertIn("does not address the question", prompt)
        self.assertIn("BODY", prompt)

    def test_part_and_combining_scopes_are_distinct(self):
        part = _summary_prompt("BODY", "Q?", part=(2, 3))
        combining = _summary_prompt("BODY", "Q?", combining=True)
        self.assertIn("part 2 of 3", part)
        self.assertIn("combine them", combining)
        self.assertNotIn("part 2 of 3", combining)


if __name__ == "__main__":
    unittest.main()


class SelectBranchSourcesTests(unittest.TestCase):
    """`SearchSession._select_branch_sources` without constructing a session."""

    @staticmethod
    def _select(config, relevances):
        from search_session import SearchSession

        session = SearchSession.__new__(SearchSession)
        session.config = config
        candidates = [
            {"relevance": score, "web_result": {"url": f"u{index}", "title": "", "source_engine": "e"}}
            for index, score in enumerate(relevances)
        ]
        kept, dropped, cutoff = SearchSession._select_branch_sources(session, candidates)
        return [c["relevance"] for c in kept], [c["relevance"] for c in dropped], cutoff

    def test_gating_disabled_keeps_everything(self):
        kept, dropped, _ = self._select({}, [0.9, 0.1])
        self.assertEqual(kept, [0.9, 0.1])
        self.assertEqual(dropped, [])

    def test_relative_margin_drops_only_the_outlier(self):
        # Measured page scores from a real branch: one strong source, two usable,
        # one off-topic. A fixed 0.5 threshold cut three of these four.
        kept, dropped, cutoff = self._select(
            {"source_relevance_margin": 0.15},
            [0.517, 0.656, 0.537, 0.467],
        )
        self.assertAlmostEqual(cutoff, 0.656 - 0.15)
        self.assertEqual(sorted(kept), [0.517, 0.537, 0.656])
        self.assertEqual(dropped, [0.467])

    def test_branch_is_never_emptied(self):
        # Every page is weak, but a thin branch must report thin evidence rather
        # than disappear.
        kept, dropped, _ = self._select(
            {"min_source_relevance": 0.5, "min_sources_per_branch": 2},
            [0.30, 0.20, 0.10],
        )
        self.assertEqual(sorted(kept, reverse=True), [0.30, 0.20])
        self.assertEqual(dropped, [0.10])

    def test_no_candidates(self):
        self.assertEqual(self._select({"source_relevance_margin": 0.15}, []), ([], [], 0.0))


class CitationAuditTests(unittest.TestCase):
    def test_separates_ledger_urls_from_a_page_s_own_outbound_links(self):
        from evidence import audit_citations

        report = (
            "Weights dominate VRAM (https://techtactician.com/llm-gpu-vram-requirements-explained/).\n"
            "See also https://techtactician.com/best-gpu-for-local-llm-ai-this-year/ for hardware.\n"
        )
        audit = audit_citations(report, [
            "https://techtactician.com/llm-gpu-vram-requirements-explained/",
            "https://arxiv.org/html/2503.09716v1",
        ])
        self.assertEqual(audit["cited_from_ledger"], ["https://techtactician.com/llm-gpu-vram-requirements-explained/"])
        self.assertEqual(audit["cited_outside_ledger"], ["https://techtactician.com/best-gpu-for-local-llm-ai-this-year/"])
        self.assertEqual(audit["ledger_urls_uncited"], ["https://arxiv.org/html/2503.09716v1"])

    def test_strips_trailing_punctuation_and_em_dashes(self):
        from evidence import audit_citations

        # Observed in a real report: "…/2607.15105—far more than…"
        audit = audit_citations(
            "as shown in https://arxiv.org/pdf/2607.15105—far more than expected.",
            ["https://arxiv.org/pdf/2607.15105"],
        )
        self.assertEqual(audit["cited_outside_ledger"], [])
        self.assertEqual(audit["cited_from_ledger"], ["https://arxiv.org/pdf/2607.15105"])

    def test_empty_report_cites_nothing(self):
        from evidence import audit_citations

        audit = audit_citations("", ["https://example.org/a"])
        self.assertEqual(audit["cited_total"], 0)
        self.assertEqual(audit["ledger_urls_uncited"], ["https://example.org/a"])
