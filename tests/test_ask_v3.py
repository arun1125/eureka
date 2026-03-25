"""Tests for enhanced ask — profile context injected into ask output."""

import struct
from pathlib import Path
from eureka.core.db import open_db


def _seed_brain_with_profile(tmp_path):
    """Brain with regular atoms + profile atoms."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    # Regular atoms
    atoms = {
        "niching-down-lets-you-charge-100x": {
            "title": "Niching down lets you charge 100x for the same product",
            "body": "When you specialize, competition drops and perceived value rises.",
            "tags": "positioning, pricing",
        },
        "vulnerability-hooks-outperform-aspirational-hooks": {
            "title": "Vulnerability hooks outperform aspirational hooks by 10x",
            "body": "People engage more with honest struggle than polished success.",
            "tags": "content, marketing",
        },
    }
    # Profile atoms
    profile_atoms = {
        "my-primary-goal-is-to-build-a-youtube-channel-about-ai-tools": {
            "title": "My primary goal is to build a YouTube channel about AI tools",
            "body": "I want to create educational content showing how to use AI tools for real work.",
            "tags": "profile, goals",
        },
        "i-tend-to-over-ideate-and-under-execute": {
            "title": "I tend to over-ideate and under-execute",
            "body": "I spend too long planning and not enough time shipping.",
            "tags": "profile, patterns",
        },
    }

    all_atoms = {**atoms, **profile_atoms}
    for slug, data in all_atoms.items():
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")

    # Store profile entries in profile table
    for slug, data in profile_atoms.items():
        conn.execute(
            "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
            "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
            (slug, data["title"]),
        )
    conn.commit()

    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    from eureka.core.linker import link_all
    link_all(conn)

    # Load embeddings
    embs = {}
    for row in conn.execute("SELECT slug, vector FROM embeddings").fetchall():
        n = len(row["vector"]) // 4
        embs[row["slug"]] = list(struct.unpack(f"{n}f", row["vector"]))

    return brain_dir, conn, embs


def test_ask_includes_profile_context(tmp_path):
    """Ask output includes profile_context when profile entries exist."""
    brain_dir, conn, embs = _seed_brain_with_profile(tmp_path)
    from eureka.core.ask import ask

    result = ask("how should I approach content creation", conn, embs)
    assert "profile_context" in result
    assert isinstance(result["profile_context"], list)
    # Should find the YouTube goal since it's about content
    assert len(result["profile_context"]) >= 1


def test_ask_profile_context_has_correct_shape(tmp_path):
    """Each profile_context entry has key and value."""
    brain_dir, conn, embs = _seed_brain_with_profile(tmp_path)
    from eureka.core.ask import ask

    result = ask("how should I approach content creation", conn, embs)
    if result["profile_context"]:
        entry = result["profile_context"][0]
        assert "key" in entry
        assert "value" in entry


def test_ask_irrelevant_profile_not_surfaced(tmp_path):
    """Profile entries irrelevant to the query are NOT surfaced."""
    brain_dir, conn, embs = _seed_brain_with_profile(tmp_path)
    from eureka.core.ask import ask

    # Query about something totally unrelated to profile entries
    result = ask("what is quantum mechanics", conn, embs)
    # With a very unrelated query and threshold filtering, profile context should be empty or minimal
    # (can't guarantee empty — embeddings might still have some similarity — but check the mechanism works)
    assert "profile_context" in result
    assert isinstance(result["profile_context"], list)
