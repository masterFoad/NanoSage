"""Filesystem boundary helpers for NanoSage output artifacts."""

from __future__ import annotations

from pathlib import Path


def safe_resolve_under(base_dir: str | Path, *parts: str | Path) -> Path:
    """
    Resolve a path and assert it stays inside ``base_dir``.

    ``base_dir`` itself may be absolute or relative. All joined child paths must
    remain contained under that resolved base directory.
    """
    base = Path(base_dir).expanduser().resolve()
    candidate = base.joinpath(*map(Path, parts)).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"Refusing to write outside output root: {candidate}")
    return candidate


def ensure_dir_under(base_dir: str | Path, *parts: str | Path) -> Path:
    """Create and return a directory that is guaranteed to live under base_dir."""
    path = safe_resolve_under(base_dir, *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
