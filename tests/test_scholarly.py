from __future__ import annotations

import unittest

from scholarly import (
    ScholarlyRecord,
    merge_records,
    parse_arxiv,
    parse_europepmc,
    parse_openalex,
    reconstruct_abstract,
)


class ScholarlyTests(unittest.TestCase):
    def test_reconstruct_abstract_from_inverted_index(self):
        index = {"Tardigrades": [0], "survive": [1], "desiccation": [2]}
        self.assertEqual(reconstruct_abstract(index), "Tardigrades survive desiccation")

    def test_reconstruct_abstract_handles_repeats_and_gaps(self):
        index = {"a": [0, 2], "b": [1]}
        self.assertEqual(reconstruct_abstract(index), "a b a")
        self.assertEqual(reconstruct_abstract(None), "")
        self.assertEqual(reconstruct_abstract({}), "")
        self.assertEqual(reconstruct_abstract({"x": "nope"}), "")

    def test_parse_openalex_prefers_open_access_url(self):
        payload = {"results": [{
            "title": "Anhydrobiosis",
            "doi": "https://doi.org/10.1/ABC",
            "publication_year": 2023,
            "open_access": {"oa_url": "https://repo.example/paper.pdf"},
            "primary_location": {"landing_page_url": "https://publisher.example/paywalled"},
            "abstract_inverted_index": {"Water": [0], "loss": [1]},
        }]}
        record = parse_openalex(payload, 5)[0]
        self.assertEqual(record.url, "https://repo.example/paper.pdf")
        self.assertEqual(record.doi, "10.1/ABC")
        self.assertEqual(record.abstract, "Water loss")
        self.assertEqual(record.year, 2023)

    def test_parse_europepmc_prefers_machine_readable_fulltext(self):
        payload = {"resultList": {"result": [{
            "title": "Cryptobiosis in tardigrades.",
            "abstractText": "Abstract body",
            "doi": "10.2/DEF",
            "pmcid": "PMC123",
            "isOpenAccess": "Y",
            "pubYear": "2021",
        }]}}
        record = parse_europepmc(payload, 5)[0]
        self.assertIn("PMC123/fullTextXML", record.url)
        self.assertEqual(record.title, "Cryptobiosis in tardigrades")
        self.assertEqual(record.year, 2021)

    def test_parse_europepmc_closed_access_falls_back(self):
        payload = {"resultList": {"result": [{
            "title": "Closed", "pmcid": "PMC9", "isOpenAccess": "N",
        }]}}
        self.assertIn("europepmc.org/article", parse_europepmc(payload, 5)[0].url)

    def test_parse_arxiv_reads_atom(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Tardigrade   survival</title>
            <summary>Long
            abstract</summary>
            <id>http://arxiv.org/abs/1234.5678v1</id>
            <published>2019-05-01T00:00:00Z</published>
          </entry>
        </feed>"""
        record = parse_arxiv(xml, 5)[0]
        self.assertEqual(record.title, "Tardigrade survival")
        self.assertEqual(record.abstract, "Long abstract")
        self.assertEqual(record.year, 2019)

    def test_parse_arxiv_survives_malformed_xml(self):
        self.assertEqual(parse_arxiv("<not xml", 5), [])

    def test_merge_interleaves_and_dedupes_by_doi(self):
        a = [ScholarlyRecord("A", "", doi="10.1/x", source="openalex"),
             ScholarlyRecord("B", "b", source="openalex")]
        b = [ScholarlyRecord("A dup", "richer abstract", doi="10.1/X", source="europepmc")]
        merged = merge_records([a, b], 10)
        self.assertEqual(len(merged), 2)
        # The duplicate carrying an abstract wins: that is what makes it evidence.
        self.assertEqual(merged[0].abstract, "richer abstract")

    def test_merge_respects_limit_and_skips_empty_groups(self):
        group = [ScholarlyRecord(f"T{i}", "x", doi=f"10.1/{i}") for i in range(5)]
        self.assertEqual(len(merge_records([group, []], 3)), 3)
        self.assertEqual(merge_records([], 5), [])


class ResultScoringTests(unittest.TestCase):
    """Ranking must respond to topical relevance, not just domain reputation."""

    def test_multiword_query_scores_on_term_overlap(self):
        from web_crawler import SearchResult, score_result

        query = "tardigrade anhydrobiosis molecular mechanisms desiccation"
        on_topic = SearchResult(
            title="Anhydrobiosis in tardigrades: molecular mechanisms of desiccation tolerance",
            href="https://europepmc.org/article/PMC/PMC1", body="tardigrade trehalose")
        off_topic = SearchResult(
            title="Entanglement between superconducting qubits and a microwave cavity",
            href="http://arxiv.org/abs/2112.07978", body="quantum circuit")
        # arxiv.org is a GOOD_DOMAIN, so the off-topic paper carries a domain bonus.
        # Term overlap must still put the on-topic paper ahead of it.
        self.assertGreater(score_result(on_topic, query), score_result(off_topic, query))

    def test_term_overlap_is_fractional(self):
        from web_crawler import _term_overlap

        self.assertEqual(_term_overlap(["alpha", "beta"], "alpha only"), 0.5)
        self.assertEqual(_term_overlap(["alpha"], "alpha"), 1.0)
        self.assertEqual(_term_overlap([], "anything"), 0.0)


if __name__ == "__main__":
    unittest.main()
