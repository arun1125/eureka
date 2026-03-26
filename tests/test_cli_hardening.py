"""Tests for agent CLI hardening: --help, --dry-run, --stdin, actionable errors, idempotent discover."""

import json
import shutil
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eureka.core.db import open_db
from eureka.core.index import rebuild_index
from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
from eureka.core.linker import link_all

FIXTURES = Path(__file__).parent / "fixtures"

MOCK_MOLECULE_RESPONSE = """# Stress and subtraction both build antifragility through removal

Hormesis makes you stronger by removing weakness through controlled stress.
Via negativa makes you wiser by removing bad options. Both achieve robustness
through subtraction — what you take away matters more than what you add.
[[hormesis-and-stressors]] [[via-negativa]] [[antifragility-defined]]

eli5: Getting rid of bad stuff makes you stronger than adding good stuff.
"""


def _setup_rich_brain(tmp_path):
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(parents=True)
    (brain_dir / "molecules").mkdir()
    (brain_dir / "brain.json").write_text("{}")
    for f in FIXTURES.glob("*.md"):
        shutil.copy(f, atoms_dir / f.name)
    conn = open_db(brain_dir)
    rebuild_index(conn, brain_dir)
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    link_all(conn)
    return brain_dir, conn


# --- Task 1: Per-command --help ---

class TestCommandHelp:
    def test_ingest_help_exits_zero(self, monkeypatch):
        """eureka ingest --help should exit 0 and print help to stderr."""
        monkeypatch.setattr("sys.argv", ["eureka", "ingest", "--help"])
        err = StringIO()
        monkeypatch.setattr("sys.stderr", err)
        from eureka.cli import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        output = err.getvalue()
        assert "Usage:" in output
        assert "Examples:" in output
        assert "--brain-dir" in output

    def test_discover_help_shows_dry_run(self, monkeypatch):
        """eureka discover --help should mention --dry-run."""
        monkeypatch.setattr("sys.argv", ["eureka", "discover", "-h"])
        err = StringIO()
        monkeypatch.setattr("sys.stderr", err)
        from eureka.cli import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        assert "--dry-run" in err.getvalue()

    def test_dump_help_shows_stdin(self, monkeypatch):
        """eureka dump --help should mention --stdin."""
        monkeypatch.setattr("sys.argv", ["eureka", "dump", "--help"])
        err = StringIO()
        monkeypatch.setattr("sys.stderr", err)
        from eureka.cli import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        assert "--stdin" in err.getvalue()

    def test_help_does_not_pollute_stdout(self, monkeypatch):
        """Help goes to stderr, stdout stays clean for JSON."""
        monkeypatch.setattr("sys.argv", ["eureka", "status", "--help"])
        out = StringIO()
        monkeypatch.setattr("sys.stdout", out)
        err = StringIO()
        monkeypatch.setattr("sys.stderr", err)
        from eureka.cli import main
        with pytest.raises(SystemExit):
            main()
        assert out.getvalue() == ""  # stdout clean
        assert "Usage:" in err.getvalue()


# --- Task 2: --dry-run for discover ---

class TestDiscoverDryRun:
    def test_dry_run_returns_candidates_without_molecules(self, tmp_path, monkeypatch):
        """--dry-run returns candidates but doesn't write molecules."""
        brain_dir, conn = _setup_rich_brain(tmp_path)

        mock_llm = MagicMock()
        mock_llm.generate.return_value = MOCK_MOLECULE_RESPONSE

        from eureka.commands import discover as discover_mod
        monkeypatch.setattr(discover_mod, "get_llm", lambda brain_dir: mock_llm)

        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        discover_mod.run_discover(str(brain_dir), dry_run=True)

        output = json.loads(buf.getvalue().strip())
        assert output["ok"] is True
        assert output["data"]["dry_run"] is True
        assert output["data"]["molecules_written"] == 0
        assert "candidates" in output["data"]
        # LLM should NOT have been called
        mock_llm.generate.assert_not_called()
        # No molecules in DB
        mol_count = conn.execute("SELECT COUNT(*) FROM molecules").fetchone()[0]
        assert mol_count == 0

    def test_dry_run_still_logs_discovery_run(self, tmp_path, monkeypatch):
        """Dry run should still log the discovery run."""
        brain_dir, conn = _setup_rich_brain(tmp_path)

        from eureka.commands import discover as discover_mod
        monkeypatch.setattr(discover_mod, "get_llm", lambda bd: None)

        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        discover_mod.run_discover(str(brain_dir), dry_run=True)

        runs = conn.execute("SELECT * FROM discovery_runs").fetchall()
        assert len(runs) == 1


# --- Task 3: --stdin for dump ---

class TestStdinSupport:
    def test_dump_without_stdin_or_arg_errors(self, monkeypatch):
        """eureka dump with no text and no --stdin should give 'Missing text' error."""
        monkeypatch.setattr("sys.argv", ["eureka", "dump"])
        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        from eureka.cli import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        output = json.loads(buf.getvalue().strip())
        assert "Missing text" in output["data"]["message"]
        assert "usage" in output["data"]

    def test_dump_stdin_empty_errors(self, monkeypatch):
        """eureka dump --stdin with empty stdin should error."""
        monkeypatch.setattr("sys.argv", ["eureka", "dump", "--stdin", "--brain-dir", "/tmp/x"])
        monkeypatch.setattr("sys.stdin", StringIO(""))
        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        from eureka.cli import main
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        output = json.loads(buf.getvalue().strip())
        assert "No input" in output["data"]["message"]


# --- Task 4: Actionable error messages ---

class TestActionableErrors:
    def test_missing_brain_dir_has_usage_and_hint(self, monkeypatch):
        """Missing brain-dir error should include usage and hint fields."""
        monkeypatch.setattr("sys.argv", ["eureka", "discover"])
        monkeypatch.delenv("EUREKA_BRAIN", raising=False)
        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        from eureka.cli import main
        with pytest.raises(SystemExit):
            main()
        output = json.loads(buf.getvalue().strip())
        assert output["ok"] is False
        assert "usage" in output["data"]
        assert "hint" in output["data"]
        assert "EUREKA_BRAIN" in output["data"]["hint"]

    def test_missing_ingest_source_has_hint(self, monkeypatch):
        """Missing ingest source should suggest --stdin."""
        monkeypatch.setattr("sys.argv", ["eureka", "ingest"])
        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        from eureka.cli import main
        with pytest.raises(SystemExit):
            main()
        output = json.loads(buf.getvalue().strip())
        assert "usage" in output["data"]
        assert "--stdin" in output["data"].get("hint", "")


# --- Task 5: Idempotent discover ---

class TestIdempotentDiscover:
    def test_existing_atom_combo_is_skipped(self, tmp_path, monkeypatch):
        """If an atom combination already exists as a molecule, skip it."""
        brain_dir, conn = _setup_rich_brain(tmp_path)

        # Pre-insert a molecule with a known atom combination
        conn.execute(
            "INSERT INTO molecules (slug, title, review_status) VALUES (?, ?, 'accepted')",
            ("existing-mol", "Existing Molecule"),
        )
        # Get first two atom slugs to pre-occupy their combination
        atom_slugs = [r["slug"] for r in conn.execute("SELECT slug FROM atoms LIMIT 2").fetchall()]
        for s in atom_slugs:
            conn.execute(
                "INSERT OR IGNORE INTO molecule_atoms (molecule_slug, atom_slug) VALUES (?, ?)",
                ("existing-mol", s),
            )
        conn.commit()

        mock_llm = MagicMock()
        mock_llm.generate.return_value = MOCK_MOLECULE_RESPONSE

        from eureka.commands import discover as discover_mod
        monkeypatch.setattr(discover_mod, "get_llm", lambda bd: mock_llm)

        buf = StringIO()
        monkeypatch.setattr("sys.stdout", buf)
        discover_mod.run_discover(str(brain_dir), dry_run=True)

        output = json.loads(buf.getvalue().strip())
        # Verify the pre-occupied combo doesn't appear in candidates
        for c in output["data"].get("candidates", []):
            assert frozenset(c["atoms"]) != frozenset(atom_slugs), \
                f"Candidate {c['atoms']} should have been filtered (already exists as molecule)"
