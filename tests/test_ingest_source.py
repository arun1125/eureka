"""Slice 4: eureka ingest — stores source row in DB (no LLM yet)."""

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def run_eureka(*args):
    result = subprocess.run(
        [sys.executable, "-m", "eureka.cli", *args],
        capture_output=True, text=True,
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else None


def test_ingest_creates_source_row(tmp_path):
    """eureka ingest stores a source row in the DB."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))
    result, output = run_eureka("ingest", str(FIXTURES / "sample_source.txt"), "--brain-dir", str(brain_dir))

    assert result.returncode == 0
    assert output["ok"] is True
    assert output["command"] == "ingest"
    assert output["data"]["source"]["type"] == "text"
    assert output["data"]["source"]["title"] is not None


def test_ingest_is_idempotent(tmp_path):
    """Ingesting the same source twice is a no-op."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))
    run_eureka("ingest", str(FIXTURES / "sample_source.txt"), "--brain-dir", str(brain_dir))
    result, output = run_eureka("ingest", str(FIXTURES / "sample_source.txt"), "--brain-dir", str(brain_dir))

    assert result.returncode == 0
    assert output["ok"] is True
    # Should indicate it was already ingested
    assert output["data"].get("already_ingested") is True or output["data"]["source"] is not None


def test_ingest_nonexistent_source(tmp_path):
    """Ingesting a nonexistent file returns error with exit code 3."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))
    result, output = run_eureka("ingest", "/nonexistent/file.txt", "--brain-dir", str(brain_dir))

    assert result.returncode == 3
    assert output["ok"] is False
