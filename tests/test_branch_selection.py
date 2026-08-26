from __future__ import annotations

import random
import unittest

from evidence import SearchBranch, refresh_search_branch
from sampling import choose_frontier_index, partition_relative_scores


class BranchSelectionTests(unittest.TestCase):
    def test_zero_window_uses_heap_max_without_sampling(self):
        index, sampled, weight = choose_frontier_index(
            [0.9, 0.8, 0.7],
            window_size=0,
            temperature=0.25,
            rng=random.Random(4),
        )
        self.assertEqual((index, sampled, weight), (0, False, 0.0))

    def test_frontier_choice_is_seed_reproducible(self):
        first = choose_frontier_index([0.9, 0.8, 0.7], window_size=3, temperature=0.25, rng=random.Random(9))
        second = choose_frontier_index([0.9, 0.8, 0.7], window_size=3, temperature=0.25, rng=random.Random(9))
        self.assertEqual(first, second)

    def test_relative_pruning_and_all_pruned_guard(self):
        kept, cutoff, forced = partition_relative_scores(
            [0.7, 0.6, 0.2],
            margin=0.15,
            absolute_floor=None,
            fallback_count=2,
        )
        self.assertEqual(kept, [0, 1])
        self.assertFalse(forced)
        self.assertAlmostEqual(cutoff, 0.55)

        kept, cutoff, forced = partition_relative_scores(
            [0.4, 0.3, 0.2],
            margin=0.1,
            absolute_floor=0.9,
            fallback_count=2,
        )
        self.assertEqual(kept, [0, 1])
        self.assertTrue(forced)
        self.assertEqual(cutoff, 0.9)

    def test_stale_priority_is_refreshed_and_requeued(self):
        branch = SearchBranch("alpha beta", depth=1, relevance=0.8, novelty=1.0)
        refreshed, should_repush = refresh_search_branch(branch, ["alpha beta"], repush_delta=1e-6)
        self.assertLess(refreshed.priority, branch.priority)
        self.assertTrue(should_repush)


if __name__ == "__main__":
    unittest.main()
