"""Tests for goal-reality gap detection."""

from datetime import datetime, timedelta, timezone
from eureka.core.db import open_db


def test_detect_goal_gaps_finds_neglected_goal(tmp_path):
    """Profile goal with no recent matching activity surfaces a gap."""
    conn = open_db(tmp_path / "brain.db")

    # Profile goal about YouTube
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
        ("youtube-goal", "Build a YouTube channel about AI tools"),
    )
    # Recent activity is all about pricing, nothing about YouTube
    ts = datetime(2026, 3, 15, tzinfo=timezone.utc).isoformat()
    for i in range(5):
        conn.execute(
            "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
            ("dump", f"pricing-atom-{i}", None, ts),
        )
        conn.execute(
            "INSERT INTO atoms (slug, title, body) VALUES (?, ?, ?)",
            (f"pricing-atom-{i}", f"Pricing insight {i}", "pricing strategy details"),
        )
    conn.commit()

    from eureka.core.pushback import detect_goal_gaps
    gaps = detect_goal_gaps(conn)

    assert len(gaps) >= 1
    assert gaps[0]["type"] == "goal_gap"
    assert "youtube" in gaps[0]["goal"].lower() or "youtube-goal" in gaps[0]["goal_key"]


def test_detect_goal_gaps_no_gap_when_active(tmp_path):
    """Goal with recent matching activity does NOT surface as gap."""
    conn = open_db(tmp_path / "brain.db")

    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
        ("youtube-goal", "Build a YouTube channel about AI tools"),
    )
    # Recent activity about YouTube
    ts = datetime(2026, 3, 15, tzinfo=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
        ("dump", "youtube-content-strategy", None, ts),
    )
    conn.execute(
        "INSERT INTO atoms (slug, title, body) VALUES (?, ?, ?)",
        ("youtube-content-strategy", "YouTube content strategy works best with consistency", "Post weekly to build audience."),
    )
    conn.commit()

    from eureka.core.pushback import detect_goal_gaps
    gaps = detect_goal_gaps(conn)

    # YouTube goal should NOT appear as a gap since there's recent YouTube activity
    youtube_gaps = [g for g in gaps if "youtube" in g.get("goal", "").lower() or "youtube" in g.get("goal_key", "").lower()]
    assert len(youtube_gaps) == 0, "Active goal should not surface as gap"
