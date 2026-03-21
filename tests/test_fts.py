"""Slice 2: FTS — full-text search works after indexing."""

import shutil
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_brain(tmp_path):
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(parents=True)
    (brain_dir / "molecules").mkdir()
    for f in FIXTURES.glob("*.md"):
        shutil.copy(f, atoms_dir / f.name)
    conn = open_db(brain_dir)
    rebuild_index(conn, brain_dir)
    return brain_dir, conn


def test_fts_finds_atom_by_body_text(tmp_path):
    """FTS search finds atoms by body content."""
    _, conn = _setup_brain(tmp_path)
    rows = conn.execute(
        "SELECT slug FROM notes_fts WHERE notes_fts MATCH ?",
        ("intrinsic value",)
    ).fetchall()
    slugs = [r["slug"] for r in rows]
    assert "margin-of-safety-applies-engineering-redundancy-to-investing" in slugs


def test_fts_finds_atom_by_tag(tmp_path):
    """FTS search finds atoms by tag."""
    _, conn = _setup_brain(tmp_path)
    rows = conn.execute(
        "SELECT slug FROM notes_fts WHERE notes_fts MATCH ?",
        ("systems-thinking",)
    ).fetchall()
    slugs = [r["slug"] for r in rows]
    assert "antifragility-defined" in slugs
