"""Tests for eureka reflect — brain-wide self-assessment."""

import struct
from datetime import datetime, timedelta, timezone
from eureka.core.db import open_db


def _seed_brain_for_reflect(tmp_path):
    """Brain with atoms, molecules, profile, activity — enough for reflect."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    # Two clusters of atoms
    cluster_a = {
        "niching-down-lets-you-charge-100x": ("Niching down lets you charge 100x", "positioning, pricing"),
        "positioning-is-context-not-messaging": ("Positioning is context not messaging", "positioning, marketing"),
        "premium-pricing-is-a-virtuous-cycle": ("Premium pricing is a virtuous cycle", "pricing, strategy"),
    }
    cluster_b = {
        "barbell-strategy": ("Barbell strategy", "risk, strategy"),
        "antifragility-defined": ("Antifragility defined", "risk, resilience"),
    }

    for slug, (title, tags) in {**cluster_a, **cluster_b}.items():
        md = f"# {title}\n\nBody for {slug}.\n\ntags: {tags}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")

    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings
    ensure_embeddings(conn, brain_dir)
    from eureka.core.linker import link_all
    link_all(conn)

    # Add profile goal
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
        ("youtube-goal", "Build a YouTube channel about AI tools"),
    )

    # Add some activity about positioning (but not YouTube)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for i in range(5):
        ts = (base + timedelta(days=i * 3)).isoformat()
        conn.execute(
            "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
            ("dump", list(cluster_a.keys())[i % 3], None, ts),
        )

    # Add a pending molecule
    conn.execute(
        "INSERT INTO molecules (slug, title, eli5, review_status, created_at) VALUES (?, ?, ?, 'pending', datetime('now'))",
        ("pending-mol", "Pending molecule", "Something pending"),
    )

    # Add an accepted molecule from 3 weeks ago
    old_date = (datetime.now(timezone.utc) - timedelta(weeks=3)).isoformat()
    conn.execute(
        "INSERT INTO molecules (slug, title, eli5, review_status, reviewed_at, created_at) VALUES (?, ?, ?, 'accepted', ?, ?)",
        ("old-accepted", "Old accepted molecule", "Old insight", old_date, old_date),
    )

    conn.commit()
    return brain_dir, conn


def test_reflect_returns_active_topics(tmp_path):
    """Reflect identifies the most active topics."""
    brain_dir, conn = _seed_brain_for_reflect(tmp_path)
    from eureka.core.reflect import reflect

    result = reflect(conn, brain_dir)
    assert "active_topics" in result
    assert isinstance(result["active_topics"], list)
    assert len(result["active_topics"]) >= 1


def test_reflect_returns_blind_spots(tmp_path):
    """Reflect detects disconnected clusters as blind spots."""
    brain_dir, conn = _seed_brain_for_reflect(tmp_path)
    from eureka.core.reflect import reflect

    result = reflect(conn, brain_dir)
    assert "blind_spots" in result
    assert isinstance(result["blind_spots"], list)


def test_reflect_returns_goal_alignment(tmp_path):
    """Reflect compares profile goals against recent activity."""
    brain_dir, conn = _seed_brain_for_reflect(tmp_path)
    from eureka.core.reflect import reflect

    result = reflect(conn, brain_dir)
    assert "goal_alignment" in result
    assert isinstance(result["goal_alignment"], list)
    assert len(result["goal_alignment"]) >= 1
    ga = result["goal_alignment"][0]
    assert "goal" in ga
    assert "brain_coverage" in ga


def test_reflect_returns_pending_count(tmp_path):
    """Reflect includes count of pending molecules."""
    brain_dir, conn = _seed_brain_for_reflect(tmp_path)
    from eureka.core.reflect import reflect

    result = reflect(conn, brain_dir)
    assert "pending_review" in result
    assert result["pending_review"] >= 1


def test_reflect_returns_molecules_to_revisit(tmp_path):
    """Reflect surfaces accepted molecules older than 2 weeks."""
    brain_dir, conn = _seed_brain_for_reflect(tmp_path)
    from eureka.core.reflect import reflect

    result = reflect(conn, brain_dir)
    assert "molecules_to_revisit" in result
    assert isinstance(result["molecules_to_revisit"], list)
    # Our old-accepted molecule should be here
    assert len(result["molecules_to_revisit"]) >= 1


def test_reflect_returns_correct_shape(tmp_path):
    """Reflect output has all 6 fields from SPEC-v3."""
    brain_dir, conn = _seed_brain_for_reflect(tmp_path)
    from eureka.core.reflect import reflect

    result = reflect(conn, brain_dir)
    required_keys = {"active_topics", "recurring_patterns", "blind_spots",
                     "goal_alignment", "pending_review", "molecules_to_revisit"}
    assert required_keys.issubset(set(result.keys())), f"Missing keys: {required_keys - set(result.keys())}"
