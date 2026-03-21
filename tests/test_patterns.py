"""Tests for pattern detection — recurring themes across dumps."""

from datetime import datetime, timedelta, timezone
from eureka.core.db import open_db
from eureka.core.activity import log_activity


def test_detect_patterns_finds_recurring_theme(tmp_path):
    """Same topic in 3+ activities over 2+ weeks triggers pattern detection."""
    conn = open_db(tmp_path / "brain.db")

    # Simulate 3 dumps about pricing over 3 weeks
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for i in range(3):
        ts = (base + timedelta(weeks=i)).isoformat()
        conn.execute(
            "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
            ("dump", f"pricing-atom-{i}", None, ts),
        )
    conn.commit()

    # Create matching atoms so we can check topic overlap
    for i in range(3):
        conn.execute(
            "INSERT INTO atoms (slug, title, body) VALUES (?, ?, ?)",
            (f"pricing-atom-{i}", f"Pricing insight {i}", f"Something about pricing strategy {i}"),
        )
    conn.commit()

    from eureka.core.pushback import detect_patterns
    patterns = detect_patterns(conn, [f"pricing-atom-{i}" for i in range(3)])

    assert len(patterns) >= 1
    assert patterns[0]["type"] == "pattern"
    assert "slug" in patterns[0]


def test_detect_patterns_ignores_recent_burst(tmp_path):
    """3 activities on the same day don't count — needs 2+ weeks spread."""
    conn = open_db(tmp_path / "brain.db")

    # 3 dumps same day
    ts = datetime(2026, 3, 1, tzinfo=timezone.utc).isoformat()
    for i in range(3):
        conn.execute(
            "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
            ("dump", f"burst-atom-{i}", None, ts),
        )
        conn.execute(
            "INSERT INTO atoms (slug, title, body) VALUES (?, ?, ?)",
            (f"burst-atom-{i}", f"Burst {i}", f"body {i}"),
        )
    conn.commit()

    from eureka.core.pushback import detect_patterns
    patterns = detect_patterns(conn, [f"burst-atom-{i}" for i in range(3)])

    assert len(patterns) == 0, "Same-day burst should not trigger pattern"
