from __future__ import annotations

import unittest

from structured_output import (
    build_gap_subquery_prompt,
    derive_search_terms,
    generate_claims_with_fallback,
    generate_gap_subqueries_with_fallback,
    generate_subqueries_with_fallback,
    parse_claim_response,
    parse_subquery_response,
)


class FakeManager:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_json_schema(self, prompt, schema_name, schema, system_message=None):
        self.calls.append((prompt, schema_name, schema, system_message))
        if self.error:
            raise self.error
        return self.response


class StructuredOutputTests(unittest.TestCase):
    def test_parse_subqueries_deduplicates_and_limits(self):
        payload = ('{"questions":['
                   '{"question":"A?","search_terms":"alpha"},'
                   '{"question":"A?","search_terms":"alpha"},'
                   '{"question":"B?","search_terms":"beta"},'
                   '{"question":"C?","search_terms":"gamma"}]}')
        questions = parse_subquery_response(payload, 2)
        self.assertEqual(questions, [
            {"question": "A?", "search_terms": "alpha"},
            {"question": "B?", "search_terms": "beta"},
        ])

    def test_parse_subqueries_rejects_bare_strings(self):
        """The old shape must fail loudly rather than silently losing search terms."""
        with self.assertRaisesRegex(ValueError, "search_terms"):
            parse_subquery_response('{"questions":["A?","B?"]}', 2)

    def test_parse_subqueries_derives_missing_search_terms(self):
        payload = '{"questions":[{"question":"How does trehalose vitrify cytoplasm?","search_terms":"  "}]}'
        questions = parse_subquery_response(payload, 1)
        self.assertEqual(questions[0]["search_terms"], "trehalose vitrify cytoplasm")

    def test_parse_subqueries_rejects_wrong_shape(self):
        with self.assertRaisesRegex(ValueError, "questions"):
            parse_subquery_response('{"questions":"A?"}', 3)

    def test_parse_claims_accepts_claim_objects(self):
        claims = parse_claim_response('{"claims":[{"claim_text":"x","evidence_id":"ev","quote":"q"}]}')
        self.assertEqual(claims[0]["evidence_id"], "ev")

    def test_parse_claims_rejects_model_supplied_offsets(self):
        """Offsets are derived, not reported: extra fields must not slip through."""
        with self.assertRaisesRegex(ValueError, "schema"):
            parse_claim_response('{"claims":[{"claim_text":"x","evidence_id":"e","quote":"q","char_start":0}]}')

    def test_parse_claims_rejects_wrong_shape(self):
        with self.assertRaisesRegex(ValueError, "claims"):
            parse_claim_response('{"claims":"no"}')

    def test_subquery_generator_uses_manager_schema_path(self):
        manager = FakeManager({"questions": [
            {"question": "A?", "search_terms": "alpha one"},
            {"question": "B?", "search_terms": "beta two"},
        ]})
        questions = generate_subqueries_with_fallback(
            manager,
            "topic",
            count=2,
            fallback=["legacy"],
            log=lambda _: None,
        )
        self.assertEqual(questions, [
            {"question": "A?", "search_terms": "alpha one"},
            {"question": "B?", "search_terms": "beta two"},
        ])
        self.assertEqual(manager.calls[0][1], "nanosage_subqueries")
        self.assertEqual(manager.calls[0][2]["properties"]["questions"]["minItems"], 2)

    def test_subquery_generator_falls_back_on_rejection_and_invalid_shape(self):
        for manager in (
            FakeManager(error=ValueError("response_format rejected")),
            FakeManager({"questions": [
                {"question": "duplicate", "search_terms": "d"},
                {"question": "duplicate", "search_terms": "d"},
            ]}),
        ):
            questions = generate_subqueries_with_fallback(
                manager,
                "topic",
                count=2,
                fallback=["legacy"],
                log=lambda _: None,
            )
            self.assertEqual(questions, [{"question": "legacy", "search_terms": "legacy"}])

    def test_subquery_generator_can_force_legacy_path(self):
        manager = FakeManager({"questions": [{"question": "A?", "search_terms": "a"}]})
        questions = generate_subqueries_with_fallback(
            manager,
            "topic",
            count=2,
            fallback=["legacy"],
            enabled=False,
            log=lambda _: None,
        )
        self.assertEqual(questions, [{"question": "legacy", "search_terms": "legacy"}])
        self.assertEqual(manager.calls, [])

    def test_gap_prompt_targets_missing_findings_and_includes_verified_claims(self):
        prompt = build_gap_subquery_prompt(
            "How do the systems compare?",
            "The evidence does not establish memory use on either GPU.",
            ["System A uses sparse routing."],
            count=2,
        )
        self.assertIn("close gaps", prompt)
        self.assertIn("does not establish memory use", prompt)
        self.assertIn("System A uses sparse routing", prompt)
        self.assertIn("exactly 2", prompt)
        self.assertIn("search_terms", prompt)

    def test_gap_prompt_is_absent_when_branch_has_no_summary_or_claims(self):
        self.assertIsNone(build_gap_subquery_prompt("Question?", "  ", [], count=3))

    def test_gap_subquery_generator_uses_one_schema_call(self):
        manager = FakeManager({"questions": [
            {"question": "What memory measurements are missing?", "search_terms": "GPU memory measurements"},
        ]})
        questions = generate_gap_subqueries_with_fallback(
            manager,
            "How do the systems compare?",
            "Memory use was not established.",
            ["System A uses sparse routing."],
            count=1,
            fallback=[],
            log=lambda _: None,
        )
        self.assertEqual(questions[0]["search_terms"], "GPU memory measurements")
        self.assertEqual(len(manager.calls), 1)
        self.assertIn("Memory use was not established", manager.calls[0][0])

    def test_gap_subquery_generator_does_not_call_llm_for_empty_branch(self):
        manager = FakeManager(error=AssertionError("must not be called"))
        questions = generate_gap_subqueries_with_fallback(
            manager,
            "Question?",
            "",
            [],
            count=1,
            fallback=["legacy"],
            log=lambda _: None,
        )
        self.assertEqual(questions, [{"question": "legacy", "search_terms": "legacy"}])
        self.assertEqual(manager.calls, [])

    def test_claim_generator_returns_failure_instead_of_raising(self):
        claims, error = generate_claims_with_fallback(
            FakeManager(error=ValueError("unsupported")),
            "branch",
            ["Evidence ID: ev_1\nText:\nalpha"],
            log=lambda _: None,
        )
        self.assertEqual(claims, [])
        self.assertIn("unsupported", error)

    def test_claim_generator_falls_back_on_schema_invalid_json(self):
        claims, error = generate_claims_with_fallback(
            FakeManager({"claims": [{"claim_text": "missing span"}]}),
            "branch",
            ["Evidence ID: ev_1\nText:\nalpha"],
            log=lambda _: None,
        )
        self.assertEqual(claims, [])
        self.assertIn("required schema", error)


    def test_derive_search_terms_strips_question_scaffolding(self):
        terms = derive_search_terms(
            "What are the specific physiological thresholds at which tardigrades enter cryptobiosis?"
        )
        self.assertNotIn("what", terms.lower().split())
        self.assertNotIn("are", terms.lower().split())
        self.assertNotIn("specific", terms.lower().split())
        self.assertIn("tardigrades", terms.lower())
        self.assertIn("cryptobiosis", terms.lower())
        self.assertLessEqual(len(terms.split()), 8)

    def test_derive_search_terms_is_deduplicated_and_ordered(self):
        terms = derive_search_terms("Trehalose and trehalose again, then vitrification")
        self.assertEqual(terms, "Trehalose again then vitrification")

    def test_derive_search_terms_respects_max_terms(self):
        long_question = " ".join(f"term{i}" for i in range(30))
        self.assertEqual(len(derive_search_terms(long_question).split()), 8)
        self.assertEqual(len(derive_search_terms(long_question, max_terms=3).split()), 3)

    def test_derive_search_terms_handles_degenerate_input(self):
        self.assertEqual(derive_search_terms(""), "")
        self.assertTrue(derive_search_terms("what is it"))


if __name__ == "__main__":
    unittest.main()
