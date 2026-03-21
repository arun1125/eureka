"""Activity logging for eureka."""

from datetime import datetime, timezone


def log_activity(conn, type, *, slug=None, query=None):
    """Insert an activity row and commit."""
    conn.execute(
        "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
        (type, slug, query, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
