"""Result tables and run records stay out of the repository until publication is decided."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Names the pipeline writes for a run: stage records, person-level arrays, tables and the summary.
RUN_OUTPUT_PATTERNS = (
    "table_*.csv",
    "summary.md",
    "checks.json",
    "baseline.json",
    "lookback.json",
    "case_*.json",
    "*.npz",
    "*.h5",
)


def _tracked_files() -> list[str]:
    try:
        listing = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return listing.stdout.splitlines()


def test_no_run_outputs_are_tracked():
    tracked = _tracked_files()
    offending = [
        path
        for path in tracked
        if any(fnmatch.fnmatch(Path(path).name, pattern) for pattern in RUN_OUTPUT_PATTERNS)
    ]
    assert offending == [], f"run outputs are tracked: {offending}"
