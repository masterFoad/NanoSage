from __future__ import annotations

import unittest

from chunking import normalize_extracted_text
from evidence import Claim, verify_claims


class ClaimVerificationTests(unittest.TestCase):
    def test_keeps_exact_span_under_canonical_normalization(self):
        text = normalize_extracted_text("Alpha   beta gamma.")
        start = text.index("beta")
        kept, rejected = verify_claims(
            [{"claim_text": "Beta is present.", "evidence_id": "ev_1", "quote": "beta", "char_start": start, "char_end": start + 4}],
            {"ev_1": text},
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(rejected, [])
        self.assertTrue(kept[0]["kept"])

    def test_rejects_unknown_evidence(self):
        kept, rejected = verify_claims(
            [{"claim_text": "x", "evidence_id": "missing", "quote": "x", "char_start": 0, "char_end": 1}],
            {},
        )
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["rejection_reason"], "unknown_evidence_id")

    def test_absent_quote_is_rejected(self):
        text = "Alpha beta"
        kept, rejected = verify_claims(
            [{"claim_text": "x", "evidence_id": "ev_1", "quote": "Gamma"}], {"ev_1": text}
        )
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["rejection_reason"], "quote_not_found")

    def test_wrong_model_offsets_do_not_reject_a_real_quote(self):
        """Models cannot count characters; a correct quote must survive bad offsets."""
        text = "Alpha beta gamma delta."
        kept, rejected = verify_claims(
            [{"claim_text": "x", "evidence_id": "ev_1", "quote": "gamma delta.",
              "char_start": 9999, "char_end": 10001}],
            {"ev_1": text},
        )
        self.assertEqual(rejected, [])
        self.assertEqual(len(kept), 1)
        # Offsets are corrected to the true location, not echoed back.
        self.assertEqual(kept[0]["claim"]["char_start"], text.index("gamma"))
        self.assertEqual(kept[0]["claim"]["char_end"], len(text))

    def test_offsets_are_derived_when_model_omits_them(self):
        text = "Alpha beta gamma."
        kept, _ = verify_claims(
            [{"claim_text": "x", "evidence_id": "ev_1", "quote": "beta gamma."}], {"ev_1": text}
        )
        self.assertEqual(kept[0]["claim"]["char_start"], 6)
        self.assertEqual(kept[0]["claim"]["char_end"], 17)

    def test_malformed_claims_are_rejected_not_raised(self):
        kept, rejected = verify_claims([{"claim_text": "x"}, object()], {"ev_1": "text"})
        self.assertEqual(kept, [])
        self.assertEqual([item["rejection_reason"] for item in rejected], ["missing_field", "malformed_claim"])

    def test_accepts_claim_dataclass(self):
        claim = Claim("cl_1", "Alpha appears.", "ev_1", "Alpha", 0, 5)
        kept, rejected = verify_claims([claim], {"ev_1": "Alpha beta"})
        self.assertEqual(len(kept), 1)
        self.assertEqual(rejected, [])


    def test_quote_matches_when_model_rewraps_whitespace(self):
        """Canonical text keeps newlines; a model may echo the quote re-wrapped."""
        text = "Alpha line.\n\nBeta gamma delta."
        start = text.index("Beta")
        end = start + len("Beta gamma delta.")
        claim = {
            "claim_text": "beta claim",
            "evidence_id": "ev_1",
            "quote": "  Beta   gamma\ndelta.  ",
            "char_start": start,
            "char_end": end,
        }
        kept, rejected = verify_claims([claim], {"ev_1": text})
        self.assertEqual(len(kept), 1, rejected)
        self.assertEqual(rejected, [])

    def test_wrong_characters_still_rejected_after_whitespace_tolerance(self):
        text = "Alpha line.\n\nBeta gamma delta."
        start = text.index("Beta")
        claim = {
            "claim_text": "wrong",
            "evidence_id": "ev_1",
            "quote": "Beta gamma EPSILON.",
            "char_start": start,
            "char_end": start + len("Beta gamma delta."),
        }
        kept, rejected = verify_claims([claim], {"ev_1": text})
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["rejection_reason"], "quote_not_found")


if __name__ == "__main__":
    unittest.main()
