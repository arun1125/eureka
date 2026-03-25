"""Slice 9a: server — HTTP API endpoints for the dashboard."""

import json
import shutil
import threading
import time
import urllib.request
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.index import rebuild_index
from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
from eureka.core.linker import link_all
from eureka.core.server import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_rich_brain(tmp_path):
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    mol_dir = brain_dir / "molecules"
    atoms_dir.mkdir(parents=True)
    mol_dir.mkdir()
    for f in FIXTURES.glob("*.md"):
        shutil.copy(f, atoms_dir / f.name)
    conn = open_db(brain_dir)
    rebuild_index(conn, brain_dir)
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    link_all(conn)

    # Add a fake molecule for testing
    from datetime import datetime
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO molecules (slug, method, score, review_status, eli5, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("test-molecule", "triangle", 65.0, "pending",
         "This is a test insight.", "Body of the test molecule.", now)
    )
    conn.commit()
    (mol_dir / "test-molecule.md").write_text("# Test molecule\n\nBody of the test molecule.\n")

    conn.close()
    (brain_dir / "brain.json").write_text("{}")
    return brain_dir


def _fetch(url):
    """Fetch URL and return parsed JSON."""
    resp = urllib.request.urlopen(url)
    return json.loads(resp.read().decode())


def _start_server(brain_dir, port):
    """Start server in a background thread, return (thread, shutdown_fn)."""
    app = create_app(str(brain_dir))
    server = app["server_factory"](port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Wait for server to be ready
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/api/stats")
            break
        except Exception:
            time.sleep(0.1)
    return server


def test_dashboard_serves_html(tmp_path):
    """GET / serves the dashboard HTML."""
    brain_dir = _setup_rich_brain(tmp_path)
    port = 18764
    server = _start_server(brain_dir, port)
    try:
        resp = urllib.request.urlopen(f"http://localhost:{port}/")
        html = resp.read().decode()
        assert "<title>Eureka</title>" in html
        assert "tab-graph" in html
    finally:
        server.shutdown()


def test_api_stats(tmp_path):
    """GET /api/stats returns brain statistics."""
    brain_dir = _setup_rich_brain(tmp_path)
    port = 18765
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/stats")
        assert data["atoms"] >= 1
        assert "molecules" in data
        assert "edges" in data
    finally:
        server.shutdown()


def test_api_graph(tmp_path):
    """GET /api/graph returns nodes and edges for D3."""
    brain_dir = _setup_rich_brain(tmp_path)
    port = 18766
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/graph")
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 1
        # Each node has slug and type
        node = data["nodes"][0]
        assert "slug" in node
        assert "type" in node
    finally:
        server.shutdown()


def test_api_search(tmp_path):
    """GET /api/search?q=antifragility returns matching atoms."""
    brain_dir = _setup_rich_brain(tmp_path)
    port = 18767
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/search?q=antifragility")
        assert "results" in data
        assert len(data["results"]) >= 1
        assert "slug" in data["results"][0]
    finally:
        server.shutdown()


def test_api_molecules(tmp_path):
    """GET /api/molecules returns molecules with ELI5."""
    brain_dir = _setup_rich_brain(tmp_path)
    port = 18768
    server = _start_server(brain_dir, port)
    try:
        data = _fetch(f"http://localhost:{port}/api/molecules")
        assert "molecules" in data
        assert len(data["molecules"]) >= 1
        mol = data["molecules"][0]
        assert "slug" in mol
        assert "eli5" in mol
        assert "score" in mol
    finally:
        server.shutdown()


def test_api_review_post(tmp_path):
    """POST /api/review/<slug> updates molecule status."""
    brain_dir = _setup_rich_brain(tmp_path)
    port = 18769
    server = _start_server(brain_dir, port)
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/api/review/test-molecule",
            data=json.dumps({"decision": "yes"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode())
        assert data["ok"] is True
        assert data["decision"] == "accepted"
    finally:
        server.shutdown()
