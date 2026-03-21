"""Tests for activity logging."""

from eureka.core.db import open_db


def test_log_activity_writes_row(tmp_path):
    """log_activity inserts a row with correct fields."""
    from eureka.core.activity import log_activity
    conn = open_db(tmp_path / "brain.db")
    log_activity(conn, "dump", slug="some-atom")
    row = conn.execute("SELECT * FROM activity").fetchone()
    assert row is not None
    assert row["type"] == "dump"
    assert row["slug"] == "some-atom"
    assert row["timestamp"] is not None
    conn.close()


def test_log_activity_with_query(tmp_path):
    """log_activity stores query text for ask-type activities."""
    from eureka.core.activity import log_activity
    conn = open_db(tmp_path / "brain.db")
    log_activity(conn, "ask", query="how should I price")
    row = conn.execute("SELECT * FROM activity").fetchone()
    assert row["type"] == "ask"
    assert row["query"] == "how should I price"
    assert row["slug"] is None
    conn.close()


def test_log_activity_increments_count(tmp_path):
    """Multiple activities increment the count in get_stats."""
    from eureka.core.activity import log_activity
    from eureka.core.db import get_stats
    conn = open_db(tmp_path / "brain.db")
    log_activity(conn, "dump", slug="a")
    log_activity(conn, "dump", slug="b")
    log_activity(conn, "ask", query="q")
    stats = get_stats(conn)
    assert stats["activity_count"] == 3
    conn.close()
