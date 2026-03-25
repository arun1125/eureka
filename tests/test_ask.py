"""Slice 7: eureka ask — graph-aware retrieval."""

import json
import shutil
from io import StringIO
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index
from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
from eureka.core.linker import link_all
from eureka.core.ask import ask

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_rich_brain(tmp_path):
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
    import struct
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    emb = {}
    for r in rows:
        dim = len(r["vector"]) // 4
        emb[r["slug"]] = list(struct.unpack(f"{dim}f", r["vector"]))
    return emb


def test_ask_returns_nearest_atoms(tmp_path, monkeypatch):
    """ask returns nearest atoms by embedding similarity."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    result = ask("How does antifragility work?", conn, embeddings)

    assert "nearest" in result
    assert len(result["nearest"]) > 0
    # Each nearest has slug and similarity
    for item in result["nearest"]:
        assert "slug" in item
        assert "similarity" in item
        assert 0.0 <= item["similarity"] <= 1.0


def test_ask_returns_graph_neighbors(tmp_path, monkeypatch):
    """ask walks the graph 1 hop to find neighbors RAG would miss."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    result = ask("What is a barbell strategy?", conn, embeddings)

    assert "graph_neighbors" in result
    # Graph neighbors should include atoms linked to the nearest atoms
    assert isinstance(result["graph_neighbors"], list)


def test_ask_returns_molecules(tmp_path, monkeypatch):
    """ask returns molecules containing retrieved atoms."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    result = ask("risk management", conn, embeddings)

    assert "molecules" in result
    assert isinstance(result["molecules"], list)


def test_ask_returns_tensions(tmp_path, monkeypatch):
    """ask surfaces V-structures (tensions) near the question."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    result = ask("decision making under uncertainty", conn, embeddings)

    assert "tensions" in result
    assert isinstance(result["tensions"], list)


def test_ask_nearest_are_relevant(tmp_path, monkeypatch):
    """Nearest atoms for a risk question should include risk-related atoms."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _setup_rich_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    result = ask("How should I manage risk in investments?", conn, embeddings)

    slugs = [item["slug"] for item in result["nearest"]]
    # At least one of the risk-related atoms should appear
    risk_atoms = {"margin-of-safety-applies-engineering-redundancy-to-investing",
                  "barbell-strategy", "antifragility-defined", "skin-in-the-game"}
    assert len(set(slugs) & risk_atoms) > 0
