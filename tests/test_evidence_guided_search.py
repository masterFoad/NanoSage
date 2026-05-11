import heapq
import unittest

from evidence import (
    SearchBranch,
    branch_priority,
    lexical_similarity,
    make_evidence_item,
    mmr_rerank,
    novelty_against,
)
from search_session import SearchSession


class EvidenceGuidedSearchTests(unittest.TestCase):
    def test_mmr_prefers_diverse_second_candidate(self):
        ranked = mmr_rerank([
            ("gpu scheduling latency", 0.95),
            ("gpu scheduling throughput", 0.94),
            ("billing anomaly detection", 0.70),
        ], lambda_relevance=0.55)
        self.assertEqual(ranked[0][0], "gpu scheduling latency")
        self.assertEqual(ranked[1][0], "billing anomaly detection")

    def test_branch_priority_penalizes_deeper_duplicate_work(self):
        shallow = branch_priority(relevance=0.8, novelty=1.0, depth=1)
        deep_duplicate = branch_priority(relevance=0.8, novelty=0.0, depth=3)
        self.assertGreater(shallow, deep_duplicate)

    def test_priority_queue_pops_highest_priority_branch_first(self):
        session = SearchSession.__new__(SearchSession)
        frontier = []
        counter = 0
        low = SearchBranch(query="low", depth=2, relevance=0.4, novelty=0.2)
        high = SearchBranch(query="high", depth=1, relevance=0.9, novelty=1.0)
        counter = session._push_branch(frontier, low, counter)
        session._push_branch(frontier, high, counter)
        _, _, popped = heapq.heappop(frontier)
        self.assertEqual(popped.query, "high")

    def test_novelty_uses_max_similarity_against_selected_queries(self):
        self.assertAlmostEqual(lexical_similarity("alpha beta", "alpha gamma"), 1 / 3)
        novelty = novelty_against("alpha beta", ["alpha gamma", "delta epsilon"])
        self.assertAlmostEqual(novelty, 2 / 3)

    def test_evidence_item_has_stable_provenance_id(self):
        page = {"url": "https://example.com/a", "file_path": "/tmp/a.html"}
        meta = {"title": "Example", "source_engine": "unit", "content_type": "text/html"}
        first = make_evidence_item(page, meta, "branch query", "snippet")
        second = make_evidence_item(page, meta, "branch query", "snippet")
        self.assertEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(first.url, page["url"])
        self.assertEqual(first.file_path, page["file_path"])
        self.assertEqual(first.branch_query, "branch query")


if __name__ == "__main__":
    unittest.main()
