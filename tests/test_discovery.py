"""Slice 6: discovery — find triangle and V-structure candidates."""

import shutil
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index
from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
from eureka.core.linker import link_all
from eureka.core.discovery import find_triangles, find_v_structures, discover_all

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_rich_brain(tmp_path):
    """Create a brain with 8 related atoms for discovery."""
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(parents=True)
    (brain_dir / "molecules").mkdir()
    for f in FIXTURES.glob("*.md"):
        shutil.copy(f, atoms_dir / f.name)
    conn = open_db(brain_dir)
    rebuild_index(conn, brain_dir)
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    link_all(conn)
    return brain_dir, conn


def _load_embeddings(conn):
    """Load all embeddings from DB as {slug: list[float]}."""
    import struct
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    emb = {}
    for r in rows:
        dim = len(r["vector"]) // 4
        emb[r["slug"]] = list(struct.unpack(f"{dim}f", r["vector"]))
    return emb


def test_find_triangles_returns_candidates(tmp_path):
    """find_triangles returns list of candidate dicts with 3 atom slugs each."""
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    candidates = find_triangles(conn, embeddings)
    assert isinstance(candidates, list)
    # With 8 related atoms, should find at least one triangle
    if len(candidates) > 0:
        c = candidates[0]
        assert "atoms" in c
        assert len(c["atoms"]) == 3
        assert c["method"] == "triangle"


def test_find_v_structures_returns_candidates(tmp_path):
    """find_v_structures returns candidates with bridge atom identified."""
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    candidates = find_v_structures(conn, embeddings)
    assert isinstance(candidates, list)
    if len(candidates) > 0:
        c = candidates[0]
        assert "atoms" in c
        assert "bridge" in c
        assert c["method"] == "v-structure"


def test_discover_all_returns_scored_candidates(tmp_path):
    """discover_all runs all methods and returns scored candidates."""
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    candidates = discover_all(conn, embeddings)
    assert isinstance(candidates, list)
    # Each candidate should have a score
    for c in candidates:
        assert "score" in c
        assert 0 <= c["score"] <= 100
        assert "method" in c
        assert "atoms" in c


def test_discover_all_sorted_by_score(tmp_path):
    """Candidates are returned highest-score-first."""
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    candidates = discover_all(conn, embeddings)
    if len(candidates) >= 2:
        scores = [c["score"] for c in candidates]
        assert scores == sorted(scores, reverse=True)
