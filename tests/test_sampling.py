from __future__ import annotations

import random
import re
import unittest
from datetime import datetime, timezone

from sampling import (
    seed_from_query_id,
    softmax_sampling_weights,
    unique_run_id,
    weighted_sample_without_replacement,
)


class SamplingTests(unittest.TestCase):
    def test_softmax_keeps_close_scores_explorable(self):
        weights = softmax_sampling_weights([0.90, 0.89, 0.88], temperature=0.25)
        total = sum(weights)
        probabilities = [weight / total for weight in weights]
        self.assertGreater(probabilities[2], 0.25)
        self.assertLess(probabilities[0] / probabilities[2], 2.0)

    def test_weighted_sample_uses_local_seeded_rng(self):
        items = ["a", "b", "c", "d"]
        weights = [1.0, 2.0, 3.0, 4.0]
        first = weighted_sample_without_replacement(items, weights, 3, random.Random(42))
        second = weighted_sample_without_replacement(items, weights, 3, random.Random(42))
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_zero_weights_are_never_selected(self):
        items = ["a", "b", "c"]
        sample = weighted_sample_without_replacement(items, [1.0, 0.0, 0.0], 3, random.Random(7))
        self.assertEqual(sample, ["a"])

    def test_unique_run_id_keeps_key_and_separates_runs(self):
        now = datetime(2026, 10, 24, 7, 30, 5, tzinfo=timezone.utc)
        self.assertEqual(unique_run_id("run_abc123", now=now, nonce="beef"), "run_abc123-20261024T073005-beef")
        # Same query, same second: the nonce still keeps two parallel runs apart.
        self.assertNotEqual(unique_run_id("run_abc123", now=now), unique_run_id("run_abc123", now=now))

    def test_unique_run_id_matches_eval_harness_pattern(self):
        run_id = unique_run_id("run_0123456789ab")
        match = re.search(r"query_id=(run_[0-9a-f]+(?:-[0-9A-Za-z]+)*)", f"query_id={run_id}, seed=1")
        self.assertEqual(match.group(1), run_id)

    def test_seed_from_query_id_is_stable(self):
        self.assertEqual(seed_from_query_id("abc123"), seed_from_query_id("abc123"))


if __name__ == "__main__":
    unittest.main()
