from __future__ import annotations

import random
import unittest

from sampling import seed_from_query_id, softmax_sampling_weights, weighted_sample_without_replacement


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

    def test_seed_from_query_id_is_stable(self):
        self.assertEqual(seed_from_query_id("abc123"), seed_from_query_id("abc123"))


if __name__ == "__main__":
    unittest.main()
