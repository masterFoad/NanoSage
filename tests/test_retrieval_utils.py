from __future__ import annotations

import unittest

from retrieval_utils import select_scored_results


class RetrievalUtilsTests(unittest.TestCase):
    def test_caps_chunk_hits_per_parent_document(self):
        entries = [
            {"metadata": {"parent_evidence_id": "a", "file_path": "/a", "chunk_index": 0}},
            {"metadata": {"parent_evidence_id": "a", "file_path": "/a", "chunk_index": 1}},
            {"metadata": {"parent_evidence_id": "other-branch", "file_path": "/a", "chunk_index": 2}},
            {"metadata": {"parent_evidence_id": "b", "file_path": "/b", "chunk_index": 0}},
        ]
        results = select_scored_results(entries, [0.9, 0.8, 0.7, 0.6], top_k=4, max_per_document=2)
        self.assertEqual(
            [result["metadata"]["parent_evidence_id"] for result in results],
            ["a", "a", "b"],
        )
        self.assertEqual([result["metadata"]["search_score"] for result in results], [0.9, 0.8, 0.6])

    def test_non_positive_limits_are_empty(self):
        entry = {"metadata": {"evidence_id": "a", "chunk_index": 0}}
        self.assertEqual(select_scored_results([entry], [1.0], top_k=0), [])
        self.assertEqual(select_scored_results([entry], [1.0], top_k=1, max_per_document=0), [])


if __name__ == "__main__":
    unittest.main()
