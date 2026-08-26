import tempfile
import unittest
import random
from pathlib import Path

import torch

from aggregator import aggregate_results
from knowledge_base import late_interaction_score, retrieve
from main import load_config
from path_utils import safe_resolve_under
from sampling import softmax_sampling_weights, weighted_sample_without_replacement


class AuditInvariantTests(unittest.TestCase):
    def test_embedding_dimension_mismatch_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "Embedding dimension mismatch"):
            late_interaction_score(torch.ones(3), torch.ones(4))

    def test_retrieve_empty_or_non_positive_top_k_is_empty(self):
        self.assertEqual(retrieve("q", [], object(), None, top_k=3, model_type="all-minilm"), [])
        self.assertEqual(retrieve("q", [], object(), None, top_k=0, model_type="all-minilm"), [])

    def test_monte_carlo_weights_are_softmax_scaled(self):
        weights = softmax_sampling_weights([0.90, 0.89, 0.88], temperature=0.25)
        self.assertEqual(len(weights), 3)
        self.assertTrue(all(weight >= 0 for weight in weights))
        probabilities = [weight / sum(weights) for weight in weights]
        self.assertGreater(probabilities[-1], 0.25)
        self.assertLess(probabilities[0] / probabilities[-1], 2.0)

    def test_weighted_sample_never_duplicates(self):
        items = ["a", "b", "c"]
        sample = weighted_sample_without_replacement(items, [1.0, 2.0, 3.0], 10, random.Random(7))
        self.assertLessEqual(len(sample), len(items))
        self.assertEqual(len(sample), len(set(sample)))

    def test_safe_path_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "root"
            base.mkdir()
            with self.assertRaisesRegex(ValueError, "outside output root"):
                safe_resolve_under(base, "..", "escape.txt")

    def test_aggregator_writes_inside_query_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = aggregate_results(
                query_id="abc123",
                enhanced_query="query",
                web_results=[],
                local_results=[],
                final_answer="answer",
                config={"results_base_dir": tmp},
            )
            output = Path(path)
            self.assertTrue(output.exists())
            self.assertIn(Path(tmp).resolve(), output.resolve().parents)
            self.assertEqual(output.parent.name, "abc123")

    def test_load_config_empty_yaml_returns_empty_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "empty.yaml"
            config.write_text("\n", encoding="utf-8")
            self.assertEqual(load_config(str(config)), {})

    def test_load_config_rejects_non_mapping_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "bad.yaml"
            config.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "YAML mapping"):
                load_config(str(config))


if __name__ == "__main__":
    unittest.main()
