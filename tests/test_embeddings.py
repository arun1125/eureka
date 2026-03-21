"""Slice 3: embeddings — embed text, cache in DB, cosine similarity."""

import shutil
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index
from eureka.core.embeddings import embed_text, ensure_embeddings, cosine_sim

FIXTURES = Path(__file__).parent / "fixtures"


ORIGINAL_3 = [
    "antifragility-defined.md",
    "barbell-strategy.md",
    "margin-of-safety-applies-engineering-redundancy-to-investing.md",
]


def _setup_brain(tmp_path):
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(parents=True)
    (brain_dir / "molecules").mkdir()
    for name in ORIGINAL_3:
        shutil.copy(FIXTURES / name, atoms_dir / name)
    conn = open_db(brain_dir)
    rebuild_index(conn, brain_dir)
    return brain_dir, conn


def test_embed_text_returns_vector():
    """embed_text returns a list of floats."""
    vec = embed_text("margin of safety in investing")
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(v, float) for v in vec)


def test_embed_text_consistent():
    """Same text produces same vector."""
    v1 = embed_text("antifragility means gaining from disorder")
    v2 = embed_text("antifragility means gaining from disorder")
    assert v1 == v2


def test_cosine_sim_identical():
    """Cosine similarity of identical vectors is 1.0."""
    vec = embed_text("barbell strategy combines safety with risk")
    sim = cosine_sim(vec, vec)
    assert abs(sim - 1.0) < 1e-6


def test_cosine_sim_related_higher_than_unrelated():
    """Related concepts have higher similarity than unrelated ones."""
    v_invest = embed_text("margin of safety applies engineering redundancy to investing")
    v_risk = embed_text("barbell strategy combines extreme safety with extreme risk")
    v_cooking = embed_text("how to make a perfect omelette with butter and herbs")

    sim_related = cosine_sim(v_invest, v_risk)
    sim_unrelated = cosine_sim(v_invest, v_cooking)
    assert sim_related > sim_unrelated


def test_ensure_embeddings_caches_in_db(tmp_path):
    """ensure_embeddings stores vectors in the embeddings table."""
    brain_dir, conn = _setup_brain(tmp_path)
    ensure_embeddings(conn, brain_dir)

    rows = conn.execute("SELECT slug FROM embeddings").fetchall()
    slugs = {r["slug"] for r in rows}
    assert "antifragility-defined" in slugs
    assert "barbell-strategy" in slugs
    assert len(slugs) == 3


def test_ensure_embeddings_is_idempotent(tmp_path):
    """Running ensure_embeddings twice doesn't duplicate rows."""
    brain_dir, conn = _setup_brain(tmp_path)
    ensure_embeddings(conn, brain_dir)
    ensure_embeddings(conn, brain_dir)

    count = conn.execute("SELECT COUNT(*) as c FROM embeddings").fetchone()["c"]
    assert count == 3
