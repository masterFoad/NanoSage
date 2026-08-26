from __future__ import annotations

import unittest

from search_session import SearchSession


class SequenceManager:
    def __init__(self, responses, enhanced_query="expanded branch"):
        self.responses = list(responses)
        self.enhanced_query = enhanced_query
        self.schema_calls = []
        self.enhance_calls = []

    def generate_json_schema(self, prompt, schema_name, schema, system_message=None):
        self.schema_calls.append((prompt, schema_name, schema, system_message))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def enhance_query(self, query):
        self.enhance_calls.append(query)
        return self.enhanced_query


def chunk_entry(evidence_id, chunk_index, text):
    return {
        "metadata": {
            "parent_evidence_id": evidence_id,
            "chunk_index": chunk_index,
            "char_start": chunk_index * 10,
            "char_end": chunk_index * 10 + len(text),
            "type": "webchunk",
            "text": text,
            "url": f"https://{evidence_id}.test",
        }
    }


class BranchAlgorithmTests(unittest.TestCase):
    def test_claim_extraction_keeps_other_batches_when_one_call_fails(self):
        claim = {"claim_text": "Alpha is present", "evidence_id": "ev-a", "quote": "Alpha"}
        manager = SequenceManager([
            {"claims": [claim]},
            ValueError("temporary schema failure"),
            {"claims": [dict(claim)]},
        ])
        session = SearchSession.__new__(SearchSession)
        session.config = {
            "claim_extraction_char_budget": 100,
            "max_claim_extraction_calls_per_branch": 3,
        }
        session.llm_manager = manager
        entries = [
            chunk_entry("ev-a", 0, "Alpha"),
            chunk_entry("ev-b", 0, "Beta"),
            chunk_entry("ev-c", 0, "Gamma"),
        ]

        claims, failures, calls, covered = session._extract_claims_for_branch("branch", entries)

        self.assertEqual(claims, [claim])
        self.assertEqual(failures, [{"call_index": 2, "reason": "temporary schema failure"}])
        self.assertEqual(calls, 3)
        self.assertEqual(covered, 3)

    def test_gap_expansion_replaces_enhancement_call_when_findings_exist(self):
        manager = SequenceManager([{"questions": [{
            "question": "Which memory measurements remain missing?",
            "search_terms": "GPU memory measurements",
        }]}])
        session = SearchSession.__new__(SearchSession)
        session.config = {"structured_subqueries": True, "subquery_count": 1}
        session.llm_manager = manager

        children = session._generate_branch_expansion(
            "How do the systems compare?",
            "The evidence did not establish memory use.",
            [{"claim": {"claim_text": "System A uses sparse routing."}, "kept": True}],
        )

        self.assertEqual(children[0]["search_terms"], "GPU memory measurements")
        self.assertEqual(manager.enhance_calls, [])
        self.assertEqual(len(manager.schema_calls), 1)

    def test_empty_branch_uses_existing_enhance_then_subquery_path(self):
        manager = SequenceManager([{"questions": [{
            "question": "What evidence can answer the branch?",
            "search_terms": "branch answer evidence",
        }]}])
        session = SearchSession.__new__(SearchSession)
        session.config = {"structured_subqueries": True, "subquery_count": 1}
        session.llm_manager = manager

        children = session._generate_branch_expansion("empty branch", "", [])

        self.assertEqual(manager.enhance_calls, ["empty branch"])
        self.assertEqual(len(manager.schema_calls), 1)
        self.assertEqual(children[0]["question"], "What evidence can answer the branch?")


if __name__ == "__main__":
    unittest.main()
