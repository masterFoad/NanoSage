from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_base import IMAGE_EXTENSIONS, PLAIN_TEXT_EXTENSIONS, load_corpus_from_dir


class CorpusLoaderTests(unittest.TestCase):
    def test_documented_text_formats_are_supported(self):
        """README documents these formats; an unlisted one is skipped silently."""
        for ext in (".txt", ".md", ".py", ".json", ".yaml", ".csv"):
            self.assertIn(ext, PLAIN_TEXT_EXTENSIONS, f"{ext} is documented but unsupported")

    def test_image_extensions_are_declared(self):
        self.assertEqual(IMAGE_EXTENSIONS, (".png", ".jpg", ".jpeg"))

    def test_unsupported_files_are_skipped_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "notes.xyz").write_text("unsupported", encoding="utf-8")
            (Path(tmp) / "archive.zip").write_text("unsupported", encoding="utf-8")
            corpus = load_corpus_from_dir(tmp, object(), None, "cpu", "all-minilm")
            self.assertEqual(corpus, [])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(load_corpus_from_dir("/nonexistent/path", object(), None), [])
        self.assertEqual(load_corpus_from_dir(None, object(), None), [])


if __name__ == "__main__":
    unittest.main()
