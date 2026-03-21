"""Slice 3: linker — compute top-N similarity edges per atom."""

import shutil
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index
from eureka.core.embeddings import ensure_embeddings
from eureka.core.linker import link_all

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
    ensure_embeddings(conn, brain_dir)
    return brain_dir, conn


def test_link_all_creates_edges_with_similarity(tmp_path):
    """link_all creates edges with non-null similarity scores."""
    brain_dir, conn = _setup_brain(tmp_path)
    link_all(conn)

    edges = conn.execute("SELECT source, target, similarity FROM edges WHERE similarity IS NOT NULL").fetchall()
    assert len(edges) > 0
    for e in edges:
        assert 0.0 <= e["similarity"] <= 1.0


def test_link_all_max_10_edges_per_node(tmp_path):
    """Each atom has at most 10 outgoing similarity edges."""
    brain_dir, conn = _setup_brain(tmp_path)
    link_all(conn)

    slugs = [r["slug"] for r in conn.execute("SELECT slug FROM atoms").fetchall()]
    for slug in slugs:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM edges WHERE source = ? AND similarity IS NOT NULL",
            (slug,)
        ).fetchone()["c"]
        assert count <= 10


def test_link_all_is_idempotent(tmp_path):
    """Running link_all twice doesn't duplicate edges."""
    brain_dir, conn = _setup_brain(tmp_path)
    link_all(conn)
    count1 = conn.execute("SELECT COUNT(*) as c FROM edges WHERE similarity IS NOT NULL").fetchone()["c"]
    link_all(conn)
    count2 = conn.execute("SELECT COUNT(*) as c FROM edges WHERE similarity IS NOT NULL").fetchone()["c"]
    assert count1 == count2


def test_link_all_related_atoms_have_high_similarity(tmp_path):
    """Atoms about related topics (investing/risk) have similarity > 0.5."""
    brain_dir, conn = _setup_brain(tmp_path)
    link_all(conn)

    row = conn.execute(
        "SELECT similarity FROM edges WHERE source = ? AND target = ?",
        ("margin-of-safety-applies-engineering-redundancy-to-investing", "barbell-strategy")
    ).fetchone()
    # They should be linked (related topics) with decent similarity
    assert row is not None
    assert row["similarity"] > 0.5
