"""Slice 2: index — sync .md files into the database."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index

FIXTURES = Path(__file__).parent / "fixtures"


ORIGINAL_3 = [
    "antifragility-defined.md",
    "barbell-strategy.md",
    "margin-of-safety-applies-engineering-redundancy-to-investing.md",
]


def _setup_brain(tmp_path):
    """Create a brain dir with 3 fixture atoms."""
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(parents=True)
    (brain_dir / "molecules").mkdir()
    for name in ORIGINAL_3:
        shutil.copy(FIXTURES / name, atoms_dir / name)
    conn = open_db(brain_dir)
    return brain_dir, conn


def test_rebuild_index_inserts_atoms(tmp_path):
    """rebuild_index populates atoms table from .md files."""
    brain_dir, conn = _setup_brain(tmp_path)
    rebuild_index(conn, brain_dir)

    rows = conn.execute("SELECT slug FROM atoms ORDER BY slug").fetchall()
    slugs = [r["slug"] for r in rows]
    assert "margin-of-safety-applies-engineering-redundancy-to-investing" in slugs
    assert "antifragility-defined" in slugs
    assert "barbell-strategy" in slugs
    assert len(slugs) == 3


def test_rebuild_index_creates_edges_from_wikilinks(tmp_path):
    """Wikilinks in .md files become edges in the DB."""
    brain_dir, conn = _setup_brain(tmp_path)
    rebuild_index(conn, brain_dir)

    edges = conn.execute("SELECT source, target FROM edges").fetchall()
    edge_set = {(r["source"], r["target"]) for r in edges}
    # margin-of-safety links to antifragility-defined and barbell-strategy
    assert ("margin-of-safety-applies-engineering-redundancy-to-investing", "antifragility-defined") in edge_set
    assert ("margin-of-safety-applies-engineering-redundancy-to-investing", "barbell-strategy") in edge_set


def test_rebuild_index_creates_tags(tmp_path):
    """Tags from .md files are stored in tags + note_tags tables."""
    brain_dir, conn = _setup_brain(tmp_path)
    rebuild_index(conn, brain_dir)

    tags = conn.execute(
        "SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id WHERE nt.slug = ?",
        ("margin-of-safety-applies-engineering-redundancy-to-investing",)
    ).fetchall()
    tag_names = {r["name"] for r in tags}
    assert tag_names == {"investing", "risk-management", "mental-models"}


def test_rebuild_index_is_idempotent(tmp_path):
    """Running rebuild_index twice doesn't duplicate atoms."""
    brain_dir, conn = _setup_brain(tmp_path)
    rebuild_index(conn, brain_dir)
    rebuild_index(conn, brain_dir)

    count = conn.execute("SELECT COUNT(*) as c FROM atoms").fetchone()["c"]
    assert count == 3


def test_rebuild_index_updates_status(tmp_path):
    """After indexing, eureka status shows correct atom count."""
    brain_dir, conn = _setup_brain(tmp_path)
    rebuild_index(conn, brain_dir)
    conn.close()

    # Also create brain.json so status works
    (brain_dir / "brain.json").write_text("{}")
    (brain_dir / ".git").mkdir(exist_ok=True)

    result = subprocess.run(
        [sys.executable, "-m", "eureka.cli", "status", str(brain_dir)],
        capture_output=True, text=True,
    )
    output = json.loads(result.stdout)
    assert output["data"]["atoms"] == 3
    assert output["data"]["edges"] > 0


def test_rebuild_index_stores_body_hash(tmp_path):
    """Each atom has a body_hash for change detection."""
    brain_dir, conn = _setup_brain(tmp_path)
    rebuild_index(conn, brain_dir)

    row = conn.execute(
        "SELECT body_hash FROM atoms WHERE slug = ?",
        ("antifragility-defined",)
    ).fetchone()
    assert row is not None
    assert len(row["body_hash"]) == 64  # SHA256
