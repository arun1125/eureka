"""Tests for historical contradiction detection — new claims vs accepted molecules + profile atoms."""

import struct
from eureka.core.db import open_db
from eureka.core.embeddings import embed_text, cosine_sim, _deterministic_embed


def _seed_brain_with_accepted_molecule(tmp_path):
    """Brain with an accepted molecule about niching down."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    # Atom that the molecule is built from
    (atoms_dir / "niching-down-lets-you-charge-100x.md").write_text(
        "# Niching down lets you charge 100x for the same product\n\n"
        "When you specialize, competition drops and perceived value rises.\n\n"
        "tags: positioning, pricing\n"
    )

    conn = open_db(brain_dir / "brain.db")
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)

    # Create an accepted molecule about specialization
    conn.execute(
        "INSERT INTO molecules (slug, title, eli5, review_status, reviewed_at, created_at) "
        "VALUES (?, ?, ?, 'accepted', '2026-03-01', '2026-03-01')",
        ("specialize-to-win", "Specialize to win", "Narrow focus beats broad effort"),
    )
    conn.execute(
        "INSERT INTO molecule_atoms (molecule_slug, atom_slug) VALUES (?, ?)",
        ("specialize-to-win", "niching-down-lets-you-charge-100x"),
    )
    # Also embed the molecule title for comparison
    mol_vec = embed_text("Specialize to win — narrow focus beats broad effort")
    vec_bytes = struct.pack(f"{len(mol_vec)}f", *mol_vec)
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (slug, model, vector, updated) VALUES (?, ?, ?, ?)",
        ("specialize-to-win", "bge-small-en-v1.5", vec_bytes, 0.0),
    )
    conn.commit()

    return brain_dir, conn


def _load_embeddings(conn):
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    embs = {}
    for row in rows:
        n = len(row["vector"]) // 4
        embs[row["slug"]] = list(struct.unpack(f"{n}f", row["vector"]))
    return embs


def test_detect_historical_contradictions_vs_molecule(tmp_path):
    """New atom contradicting an accepted molecule is flagged with date and slug."""
    brain_dir, conn = _seed_brain_with_accepted_molecule(tmp_path)
    existing_embs = _load_embeddings(conn)

    # New atom opposing specialization
    new_vec = embed_text("Staying broad is underrated because specialists miss adjacent opportunities")
    new_embeddings = {"staying-broad-is-underrated": new_vec}

    from eureka.core.pushback import detect_historical_contradictions
    contradictions = detect_historical_contradictions(conn, new_embeddings, existing_embs)

    assert len(contradictions) >= 1
    c = contradictions[0]
    assert c["type"] == "historical_contradiction"
    assert "new_atom" in c
    assert "existing_slug" in c
    assert "date" in c  # when the molecule was accepted


def test_detect_historical_contradictions_vs_profile(tmp_path):
    """New atom contradicting a profile atom is flagged."""
    brain_dir, conn = _seed_brain_with_accepted_molecule(tmp_path)

    # Add a profile atom
    (brain_dir / "atoms" / "i-believe-in-deep-specialization.md").write_text(
        "# I believe in deep specialization\n\nBeing the best at one thing beats being good at many.\n\ntags: profile, values\n"
    )
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)

    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, '2026-02-15', '2026-02-15')",
        ("i-believe-in-deep-specialization", "I believe in deep specialization"),
    )
    conn.commit()

    existing_embs = _load_embeddings(conn)

    new_vec = embed_text("Generalists outperform specialists in complex environments")
    new_embeddings = {"generalists-outperform-specialists": new_vec}

    from eureka.core.pushback import detect_historical_contradictions
    contradictions = detect_historical_contradictions(conn, new_embeddings, existing_embs)

    # Should flag contradiction against profile atom or molecule
    assert len(contradictions) >= 1
    assert any(c["type"] == "historical_contradiction" for c in contradictions)
