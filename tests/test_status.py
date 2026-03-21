"""Slice 1: eureka status — returns brain stats as JSON."""

import json
import subprocess
import sys


def run_eureka(*args):
    """Run eureka CLI and return parsed JSON output."""
    result = subprocess.run(
        [sys.executable, "-m", "eureka.cli", *args],
        capture_output=True,
        text=True,
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else None


def test_status_empty_brain(tmp_path):
    """Status on an empty brain returns all zeros."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))
    result, output = run_eureka("status", str(brain_dir))

    assert result.returncode == 0
    assert output["ok"] is True
    assert output["command"] == "status"
    assert output["data"]["atoms"] == 0
    assert output["data"]["molecules"]["total"] == 0
    assert output["data"]["sources"] == 0
    assert output["data"]["edges"] == 0


def test_status_no_brain_returns_error(tmp_path):
    """Status on a nonexistent brain returns error with exit code 3."""
    brain_dir = tmp_path / "nonexistent"
    result, output = run_eureka("status", str(brain_dir))

    assert result.returncode == 3
    assert output["ok"] is False
    assert len(output["errors"]) > 0
