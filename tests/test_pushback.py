"""Tests for pushback engine — contradiction detection + gap detection."""

from pathlib import Path
from eureka.core.db import open_db
from eureka.core.embeddings import embed_text, cosine_sim, _deterministic_embed


def _seed_brain_with_contradiction(tmp_path):
    """Brain with atoms that will contradict a dump about 'staying broad'."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    atoms = {
        "niching-down-lets-you-charge-100x": {
            "title": "Niching down lets you charge 100x for the same product",
            "body": "When you specialize in a narrow market, competition drops and perceived value rises. Generalists compete on price. Specialists compete on expertise.",
            "tags": "positioning, pricing",
        },
        "specialize-in-a-niche-like-organisms-in-an-ecosystem": {
            "title": "Specialize in a niche like organisms in an ecosystem",
            "body": "Species survive by specializing. The generalist gets outcompeted by every specialist in every niche. Same in business.",
            "tags": "positioning, strategy",
        },
        "barbell-strategy": {
            "title": "Barbell strategy",
            "body": "Put 90% in safe assets and 10% in high-risk bets. Avoid the middle.",
            "tags": "risk, strategy",
        },
    }
    for slug, data in atoms.items():
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    from eureka.core.linker import link_all
    link_all(conn)

    return brain_dir, conn


def _load_embeddings(conn):
    """Load all embeddings from DB."""
    import struct
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    embs = {}
    for row in rows:
        n = len(row["vector"]) // 4
        embs[row["slug"]] = list(struct.unpack(f"{n}f", row["vector"]))
    return embs


def test_find_contradictions_detects_opposing_claims(tmp_path):
    """An atom about 'staying broad beats niching' should contradict 'niching down lets you charge 100x'."""
    brain_dir, conn = _seed_brain_with_contradiction(tmp_path)
    existing_embs = _load_embeddings(conn)

    # Simulate a new atom that opposes niching
    new_atom_text = "Staying broad is underrated because specialists miss adjacent opportunities"
    new_vec = embed_text(new_atom_text)
    new_embeddings = {"staying-broad-is-underrated": new_vec}

    from eureka.core.pushback import find_contradictions
    contradictions = find_contradictions(new_embeddings, existing_embs, conn)

    # Should find at least one contradiction with the niche-related atoms
    assert len(contradictions) > 0
    existing_slugs_flagged = [c["existing_atom"] for c in contradictions]
    assert any("niche" in s or "specialize" in s for s in existing_slugs_flagged), \
        f"Expected niche-related contradiction, got: {existing_slugs_flagged}"


def test_find_contradictions_returns_correct_shape(tmp_path):
    """Each contradiction has new_atom, existing_atom, similarity, note."""
    brain_dir, conn = _seed_brain_with_contradiction(tmp_path)
    existing_embs = _load_embeddings(conn)

    new_vec = embed_text("Staying broad beats niching down every time")
    new_embeddings = {"staying-broad-beats-niching": new_vec}

    from eureka.core.pushback import find_contradictions
    contradictions = find_contradictions(new_embeddings, existing_embs, conn)

    if contradictions:
        c = contradictions[0]
        assert "new_atom" in c
        assert "existing_atom" in c
        assert "similarity" in c
        assert isinstance(c["similarity"], float)


def test_find_gaps_detects_sparse_topics(tmp_path):
    """Dump near a topic with very few atoms surfaces a gap."""
    brain_dir, conn = _seed_brain_with_contradiction(tmp_path)
    existing_embs = _load_embeddings(conn)

    # Dump about psychology — brain has nothing on this
    new_vec = embed_text("Cognitive behavioral therapy restructures automatic thoughts")
    new_embeddings = {"cbt-restructures-thoughts": new_vec}

    from eureka.core.pushback import find_gaps
    gaps = find_gaps(new_embeddings, existing_embs, conn)

    # Should detect that psychology/therapy is a sparse area
    assert len(gaps) > 0
    assert "topic" in gaps[0]


def test_dump_includes_tensions_and_gaps(tmp_path):
    """process_dump output includes tensions and gaps arrays."""
    brain_dir, conn = _seed_brain_with_contradiction(tmp_path)

    class FakeLLM:
        def generate(self, prompt):
            return """# Staying broad is underrated because specialists miss adjacent opportunities

Generalists spot connections across domains that specialists never see.

tags: positioning, strategy"""

    from eureka.core.dump import process_dump
    result = process_dump(
        raw_text="I think staying broad is underrated",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    assert "tensions" in result
    assert "gaps" in result
    assert isinstance(result["tensions"], list)
    assert isinstance(result["gaps"], list)
