"""Tests for enhanced ask — reframes, action suggestions, pushback."""

import struct
from eureka.core.db import open_db
from eureka.core.embeddings import embed_text


def _seed_brain_for_enhanced_ask(tmp_path):
    """Brain with atoms, profile, V-structures possible."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    atoms = {
        "vulnerability-hooks-outperform-aspirational-hooks": {
            "title": "Vulnerability hooks outperform aspirational hooks by 10x",
            "body": "People engage more with honest struggle than polished success stories.",
            "tags": "content, marketing",
        },
        "premium-pricing-is-a-virtuous-cycle": {
            "title": "Premium pricing is a virtuous cycle not a greed play",
            "body": "Higher prices fund better service which justifies higher prices.",
            "tags": "pricing, positioning",
        },
        "positioning-is-context-not-messaging": {
            "title": "Positioning is the context that precedes messaging not the messaging itself",
            "body": "Context determines how the message is received.",
            "tags": "positioning, marketing",
        },
        "niching-down-lets-you-charge-100x": {
            "title": "Niching down lets you charge 100x for the same product",
            "body": "Specialization reduces competition and increases perceived value.",
            "tags": "positioning, pricing",
        },
    }
    for slug, data in atoms.items():
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")

    # Profile
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
        ("youtube-goal", "Build a YouTube channel about AI tools"),
    )
    conn.commit()

    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings
    ensure_embeddings(conn, brain_dir)
    from eureka.core.linker import link_all
    link_all(conn)

    embs = {}
    for row in conn.execute("SELECT slug, vector FROM embeddings").fetchall():
        n = len(row["vector"]) // 4
        embs[row["slug"]] = list(struct.unpack(f"{n}f", row["vector"]))

    return brain_dir, conn, embs


def test_ask_includes_reframes(tmp_path):
    """Ask output includes reframes derived from V-structures."""
    brain_dir, conn, embs = _seed_brain_for_enhanced_ask(tmp_path)
    from eureka.core.ask import ask

    result = ask("should I be vulnerable or authoritative in content", conn, embs)
    assert "reframes" in result
    assert isinstance(result["reframes"], list)


def test_ask_includes_action_suggestions(tmp_path):
    """Ask output includes action suggestions based on goals + gaps."""
    brain_dir, conn, embs = _seed_brain_for_enhanced_ask(tmp_path)
    from eureka.core.ask import ask

    result = ask("how should I approach content strategy", conn, embs)
    assert "action_suggestions" in result
    assert isinstance(result["action_suggestions"], list)


def test_ask_includes_pushback(tmp_path):
    """Ask output includes pushback array."""
    brain_dir, conn, embs = _seed_brain_for_enhanced_ask(tmp_path)
    from eureka.core.ask import ask

    result = ask("I should stay broad and avoid niching", conn, embs)
    assert "pushback" in result
    assert isinstance(result["pushback"], list)


def test_ask_enhanced_shape(tmp_path):
    """Enhanced ask returns all v3 fields alongside v2 fields."""
    brain_dir, conn, embs = _seed_brain_for_enhanced_ask(tmp_path)
    from eureka.core.ask import ask

    result = ask("content strategy", conn, embs)

    # v2 fields
    assert "nearest" in result
    assert "graph_neighbors" in result
    assert "molecules" in result
    assert "tensions" in result

    # v3 fields
    assert "profile_context" in result
    assert "reframes" in result
    assert "action_suggestions" in result
    assert "pushback" in result
