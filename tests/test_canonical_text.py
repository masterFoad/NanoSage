from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from canonical_text import persist_canonical_text


class CanonicalTextTests(unittest.TestCase):
    def test_persists_normalized_utf8_sidecar_and_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            download = Path(tmp) / "page.html"
            download.write_text("source", encoding="utf-8")
            artifact = persist_canonical_text(str(download), "  café\n\n evidence\ttext  ")
            self.assertEqual(Path(artifact.path), Path(str(download) + ".extracted.txt").resolve())
            self.assertEqual(Path(artifact.path).read_text(encoding="utf-8"), "café\n\nevidence text")
            self.assertEqual(artifact.length, len(artifact.text))

    def test_persisted_text_offsets_round_trip(self):
        """Offsets must index the persisted file exactly, or span verification is meaningless."""
        with tempfile.TemporaryDirectory() as tmp:
            download = Path(tmp) / "page.html"
            download.write_text("source", encoding="utf-8")
            artifact = persist_canonical_text(str(download), "Alpha line.\n\nBeta line.\tGamma.")
            on_disk = Path(artifact.path).read_text(encoding="utf-8")
            self.assertEqual(on_disk, artifact.text)
            start = artifact.text.index("Beta")
            self.assertEqual(on_disk[start:start + 4], "Beta")


if __name__ == "__main__":
    unittest.main()
