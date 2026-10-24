from __future__ import annotations

import os
import tempfile
import types
import unittest

from evidence import audit_citations, remove_off_ledger_citations, source_kind


class SourceKindTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(source_kind("https://doi.org/10.2138/am-2017-5993ccby"), "paper")
        self.assertEqual(source_kind("https://www.sciencedirect.com/science/article/pii/X"), "paper")
        self.assertEqual(source_kind("https://ceramics.onlinelibrary.wiley.com/doi/10.1111/jace.12407"), "paper")
        self.assertEqual(source_kind("https://anything.example/x", "scholarly:openalex"), "paper")
        self.assertEqual(source_kind("https://news.mit.edu/2023/roman-concrete"), "institution")
        self.assertEqual(source_kind("https://buildmatinsight.com/concrete-cement/x"), "web page")
        # A suffix match must sit on a label boundary.
        self.assertEqual(source_kind("https://notdoi.org/x"), "web page")


class CitationRemovalTests(unittest.TestCase):
    BAD = "https://morningoverview.com/invented-slug/"

    def test_backticked_ledger_url_is_not_off_ledger(self):
        audit = audit_citations("Shown in `https://news.mit.edu/a`.", ["https://news.mit.edu/a"])
        self.assertEqual(audit["cited_outside_ledger"], [])

    def test_removes_inline_list_link_and_reference_forms(self):
        report = (
            f"Cracks heal (https://news.mit.edu/a, {self.BAD}).\n"
            f"Clasts dissolve ({self.BAD}).\n"
            f"See [the article]({self.BAD}).\n"
            "## References\n"
            "- https://news.mit.edu/a\n"
            f"- {self.BAD}\n"
            f"2. `{self.BAD}`\n"
        )
        cleaned = remove_off_ledger_citations(report, [self.BAD])
        self.assertNotIn("morningoverview", cleaned)
        self.assertIn("Cracks heal (https://news.mit.edu/a).", cleaned)
        self.assertIn("Clasts dissolve.", cleaned)
        self.assertIn("See the article.", cleaned)
        self.assertEqual(cleaned.count("https://news.mit.edu/a"), 2)
        self.assertTrue(cleaned.rstrip().endswith("- https://news.mit.edu/a"))

    def test_leaves_longer_urls_sharing_a_prefix(self):
        cleaned = remove_off_ledger_citations(f"keep {self.BAD}more/", [self.BAD])
        self.assertIn(f"{self.BAD}more/", cleaned)


class AbstractFallbackTests(unittest.TestCase):
    def test_bot_wall_page_does_not_suppress_the_abstract(self):
        from web_crawler import SearchResult, parse_pages_with_abstract_fallback

        url = "https://doi.org/10.2138/am-2017-5993ccby"
        abstract = "Roman marine concrete contains Al-tobermorite and phillipsite cements. " * 6
        result = SearchResult(title="Phillipsite and Al-tobermorite mineral cements", href=url,
                              body=abstract, source="scholarly:openalex")
        with tempfile.TemporaryDirectory() as out_dir:
            wall = os.path.join(out_dir, "wall.html")
            with open(wall, "w", encoding="utf-8") as f:
                f.write("<html><body><p>JavaScript is disabled</p><p>In order to continue, we need "
                        "to verify that you're not a robot.</p></body></html>")
            pages = [{"url": url, "file_path": wall, "content_type": "text/html", "size": 200}]
            parsed = parse_pages_with_abstract_fallback(pages, [result], {url: result}, out_dir, "roman concrete")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["fetch_tier"], "abstract")
        self.assertIn("tobermorite", parsed[0]["meta"]["text_preview"])


class ScholarlyMarginTests(unittest.TestCase):
    @staticmethod
    def _select(config, candidates):
        from search_session import SearchSession

        return SearchSession._select_branch_sources(types.SimpleNamespace(config=config), candidates)

    @staticmethod
    def _candidate(relevance, engine):
        return {"relevance": relevance, "web_result": {"source_engine": engine}}

    def test_paper_just_under_the_page_cutoff_is_kept(self):
        candidates = [
            self._candidate(0.70, "searchapi"),
            self._candidate(0.53, "scholarly:arxiv"),   # on-topic abstract
            self._candidate(0.53, "ddg"),               # equally weak web page
            self._candidate(0.30, "scholarly:arxiv"),   # off-topic paper
        ]
        kept, dropped, _ = self._select({"source_relevance_margin": 0.15}, candidates)
        self.assertEqual([c["web_result"]["source_engine"] for c in kept], ["searchapi", "scholarly:arxiv"])
        self.assertEqual(len(dropped), 2)

    def test_null_disables_and_floor_still_applies(self):
        candidates = [self._candidate(0.70, "ddg"), self._candidate(0.53, "scholarly:arxiv")]
        kept, _, _ = self._select({"source_relevance_margin": 0.15, "scholarly_relevance_margin": None,
                                   "min_sources_per_branch": 1}, candidates)
        self.assertEqual(len(kept), 1)
        kept, _, _ = self._select({"source_relevance_margin": 0.15, "min_source_relevance": 0.6,
                                   "min_sources_per_branch": 1}, candidates)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
