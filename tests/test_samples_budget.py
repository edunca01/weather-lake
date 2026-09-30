"""The committed sample stays small and is plain JSON (the full responses stay local)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_samples_are_small_json() -> None:
    files = [p for p in (ROOT / "samples").rglob("*") if p.is_file()]
    assert files
    assert all(p.suffix in {".json", ".md"} for p in files)
    assert sum(p.stat().st_size for p in files) < 1024 * 1024
