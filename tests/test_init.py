"""Slice 1: eureka init — creates a brain directory with brain.db."""

import json
import subprocess
import sys
from pathlib import Path


def run_eureka(*args, cwd=None):
    """Run eureka CLI and return parsed JSON output."""
    result = subprocess.run(
        [sys.executable, "-m", "eureka.cli", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else None


def test_init_creates_brain_dir(tmp_path):
    brain_dir = tmp_path / "mybrain"
    result, output = run_eureka("init", str(brain_dir))

    assert result.returncode == 0
    assert brain_dir.exists()
    assert (brain_dir / "brain.db").exists()
    assert (brain_dir / "atoms").is_dir()
    assert (brain_dir / "molecules").is_dir()
    assert output["ok"] is True
    assert output["command"] == "init"
    assert output["data"]["brain_dir"] == str(brain_dir)


def test_init_idempotent(tmp_path):
    """Running init twice on the same dir succeeds both times."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))
    result, output = run_eureka("init", str(brain_dir))

    assert result.returncode == 0
    assert output["ok"] is True
    # DB still works after second init
    assert (brain_dir / "brain.db").exists()


def test_init_creates_git_repo(tmp_path):
    """Init creates a git repo in the brain directory."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))

    assert (brain_dir / ".git").is_dir()


def test_init_creates_brain_json(tmp_path):
    """Init creates a brain.json config file."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))

    brain_json = brain_dir / "brain.json"
    assert brain_json.exists()
    config = json.loads(brain_json.read_text())
    assert "pipeline" in config
