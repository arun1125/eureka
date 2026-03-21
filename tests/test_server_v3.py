"""Tests for v3 API endpoints: profile, activity, reflect."""

import json
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.server import create_app


def _seed_v3_brain(tmp_path):
    """Brain with atoms, profile, activity — enough for v3 endpoints."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()
    (brain_dir / "brain.json").write_text("{}")

    (atoms_dir / "niching-down.md").write_text(
        "# Niching down lets you charge 100x\n\nSpecialize to win.\n\ntags: positioning\n"
    )

    conn = open_db(brain_dir)
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)

    # Profile
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
        ("youtube-goal", "Build a YouTube channel"),
    )
    # Activity
    conn.execute(
        "INSERT INTO activity (type, slug, query, timestamp) VALUES (?, ?, ?, ?)",
        ("dump", "niching-down", None, datetime.now(timezone.utc).isoformat()),
    )
    # Pending molecule
    conn.execute(
        "INSERT INTO molecules (slug, title, eli5, review_status, created_at) "
        "VALUES (?, ?, ?, 'pending', datetime('now'))",
        ("test-mol", "Test molecule", "Test eli5"),
    )
    conn.commit()
    conn.close()

    return brain_dir


def _fetch(url):
    resp = urllib.request.urlopen(url)
    return json.loads(resp.read().decode())


def _start_server(brain_dir, port):
    app = create_app(str(brain_dir))
    server = app["server_factory"](port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/api/stats")
            break
        except Exception:
            time.sleep(0.1)
    return server


def test_profile_endpoint(tmp_path):
    """GET /api/profile returns profile entries."""
    brain_dir = _seed_v3_brain(tmp_path)
    port = 18780
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/profile")
        assert "entries" in data
        assert len(data["entries"]) >= 1
        assert data["entries"][0]["key"] == "youtube-goal"
    finally:
        server.shutdown()


def test_activity_endpoint(tmp_path):
    """GET /api/activity returns recent activity."""
    brain_dir = _seed_v3_brain(tmp_path)
    port = 18781
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/activity")
        assert "activities" in data
        assert len(data["activities"]) >= 1
        assert data["activities"][0]["type"] == "dump"
    finally:
        server.shutdown()


def test_reflect_endpoint(tmp_path):
    """GET /api/reflect returns reflect output."""
    brain_dir = _seed_v3_brain(tmp_path)
    port = 18782
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/reflect")
        assert "active_topics" in data
        assert "pending_review" in data
        assert data["pending_review"] >= 1
    finally:
        server.shutdown()
