"""The summary is written only from passing checks at least as new as the stage outputs."""

from __future__ import annotations

import json
import os

from medikids_act.tables import summary_problem


def _write(path, text="x", mtime=None):
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_missing_checks_blocks_summary(tmp_path):
    _write(tmp_path / "baseline.npz")
    assert "no checks.json" in summary_problem(tmp_path)


def test_failed_check_blocks_summary(tmp_path):
    _write(tmp_path / "baseline.npz", mtime=1_000)
    rows = [{"check": "a", "passed": True, "detail": ""}, {"check": "b", "passed": False, "detail": ""}]
    _write(tmp_path / "checks.json", json.dumps(rows), mtime=2_000)
    assert summary_problem(tmp_path) == "1 saved checks failed"


def test_stale_checks_block_summary(tmp_path):
    _write(tmp_path / "checks.json", json.dumps([{"check": "a", "passed": True, "detail": ""}]), mtime=1_000)
    _write(tmp_path / "case_floor.npz", mtime=2_000)
    assert "older than a stage output" in summary_problem(tmp_path)


def test_fresh_passing_checks_allow_summary(tmp_path):
    _write(tmp_path / "baseline.npz", mtime=1_000)
    _write(tmp_path / "case_floor.json", mtime=1_000)
    _write(tmp_path / "checks.json", json.dumps([{"check": "a", "passed": True, "detail": ""}]), mtime=2_000)
    assert summary_problem(tmp_path) is None
