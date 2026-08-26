"""Canonical extracted-text persistence for downloaded evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chunking import normalize_extracted_text
from path_utils import safe_resolve_under


@dataclass(frozen=True)
class CanonicalTextArtifact:
    path: str
    length: int
    text: str


def persist_canonical_text(download_path: str, extracted_text: str) -> CanonicalTextArtifact:
    """Normalize once and persist UTF-8 text next to its downloaded source."""
    source = Path(download_path)
    output = safe_resolve_under(source.parent, source.name + ".extracted.txt")
    canonical = normalize_extracted_text(extracted_text)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(canonical)
    return CanonicalTextArtifact(path=str(output), length=len(canonical), text=canonical)
