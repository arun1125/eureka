"""Tests for v3 schema additions: profile + activity tables."""

import sqlite3
from pathlib import Path
from eureka.core.db import open_db


def test_profile_table_exists(tmp_path):
    """open_db creates a profile table with the correct columns."""
    conn = open_db(tmp_path / "brain.db")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile'"
    ).fetchone()
    assert row is not None, "profile table should exist"

    # Check columns
    cols = {r[1] for r in conn.execute("PRAGMA table_info(profile)").fetchall()}
    assert cols == {"key", "value", "source", "confidence", "created_at", "updated_at"}
    conn.close()


def test_activity_table_exists(tmp_path):
    """open_db creates an activity table with the correct columns."""
    conn = open_db(tmp_path / "brain.db")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='activity'"
    ).fetchone()
    assert row is not None, "activity table should exist"

    cols = {r[1] for r in conn.execute("PRAGMA table_info(activity)").fetchall()}
    assert cols == {"id", "type", "slug", "query", "timestamp"}
    conn.close()


def test_status_includes_v3_counts(tmp_path):
    """get_stats returns profile and activity counts."""
    from eureka.core.db import get_stats
    conn = open_db(tmp_path / "brain.db")
    stats = get_stats(conn)
    assert "profile_entries" in stats
    assert "activity_count" in stats
    assert stats["profile_entries"] == 0
    assert stats["activity_count"] == 0
    conn.close()
