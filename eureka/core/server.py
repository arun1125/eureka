"""HTTP API server for the Eureka dashboard."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from eureka.core.db import open_db, get_stats
from eureka.core.review import accept_molecule, reject_molecule


def create_app(brain_dir: str) -> dict:
    """Create the app dict with a server_factory callable."""
    brain_dir = Path(brain_dir)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # suppress request logging

        def _json_response(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path == "/api/stats":
                conn = open_db(brain_dir)
                try:
                    stats = get_stats(conn)
                    self._json_response(stats)
                finally:
                    conn.close()

            elif path == "/api/graph":
                conn = open_db(brain_dir)
                try:
                    # Atoms + molecules in the graph
                    all_slugs = []
                    slug_type = {}
                    slug_method = {}
                    for row in conn.execute("SELECT slug FROM atoms"):
                        all_slugs.append(row["slug"])
                        slug_type[row["slug"]] = "atom"
                    for row in conn.execute("SELECT slug, method FROM molecules"):
                        all_slugs.append(row["slug"])
                        slug_type[row["slug"]] = "molecule"
                        slug_method[row["slug"]] = row["method"]
                    atom_set = set(all_slugs)

                    # Collect atom-atom edges
                    edge_list = []
                    for row in conn.execute("SELECT source, target, similarity FROM edges"):
                        if row["source"] in atom_set and row["target"] in atom_set:
                            edge_list.append({"source": row["source"], "target": row["target"], "similarity": row["similarity"]})

                    # Connect molecules to their constituent atoms
                    for row in conn.execute("SELECT molecule_slug, atom_slug FROM molecule_atoms"):
                        if row["molecule_slug"] in atom_set and row["atom_slug"] in atom_set:
                            edge_list.append({"source": row["molecule_slug"], "target": row["atom_slug"], "similarity": 1.0})

                    # Community by primary tag (first tag on each atom)
                    community = {}
                    tag_to_id = {}
                    tag_counter = 0
                    for slug in all_slugs:
                        row = conn.execute(
                            "SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id "
                            "WHERE nt.slug = ? ORDER BY t.name LIMIT 1", (slug,)
                        ).fetchone()
                        if row:
                            tag_name = row["name"]
                            if tag_name not in tag_to_id:
                                tag_to_id[tag_name] = tag_counter
                                tag_counter += 1
                            community[slug] = tag_to_id[tag_name]
                        else:
                            community[slug] = 0

                    # Load titles for display
                    slug_title = {}
                    for row in conn.execute("SELECT slug, title FROM atoms"):
                        slug_title[row["slug"]] = row["title"]
                    for row in conn.execute("SELECT slug, title FROM molecules"):
                        slug_title[row["slug"]] = row["title"]

                    nodes = []
                    for slug in all_slugs:
                        node = {
                            "slug": slug,
                            "title": slug_title.get(slug, slug.replace("-", " ")),
                            "type": slug_type.get(slug, "atom"),
                            "community": community.get(slug, 0),
                        }
                        if slug in slug_method:
                            node["method"] = slug_method[slug]
                        nodes.append(node)

                    self._json_response({"nodes": nodes, "edges": edge_list})
                finally:
                    conn.close()

            elif path == "/api/search":
                qs = parse_qs(parsed.query)
                q = qs.get("q", [""])[0]
                tag = qs.get("tag", [""])[0]
                source_id = qs.get("source", [""])[0]
                conn = open_db(brain_dir)
                try:
                    results = []
                    if tag:
                        # Filter by tag
                        rows = conn.execute(
                            "SELECT a.slug, a.title, a.body FROM atoms a "
                            "JOIN note_tags nt ON a.slug = nt.slug "
                            "JOIN tags t ON nt.tag_id = t.id "
                            "WHERE t.name = ? ORDER BY a.title",
                            (tag,),
                        ).fetchall()
                        for row in rows:
                            results.append({
                                "slug": row["slug"],
                                "title": row["title"],
                                "snippet": (row["body"] or "")[:200],
                            })
                    elif q:
                        # Search by title LIKE (more reliable than FTS for short queries)
                        rows = conn.execute(
                            "SELECT slug, title, body FROM atoms "
                            "WHERE title LIKE ? OR body LIKE ? OR slug LIKE ? "
                            "ORDER BY title LIMIT 50",
                            (f"%{q}%", f"%{q}%", f"%{q}%"),
                        ).fetchall()
                        for row in rows:
                            results.append({
                                "slug": row["slug"],
                                "title": row["title"],
                                "snippet": (row["body"] or "")[:200],
                            })
                    else:
                        # No filter — return all atoms
                        rows = conn.execute(
                            "SELECT slug, title, body FROM atoms ORDER BY title LIMIT 100"
                        ).fetchall()
                        for row in rows:
                            results.append({
                                "slug": row["slug"],
                                "title": row["title"],
                                "snippet": (row["body"] or "")[:200],
                            })

                    # Get all tags and sources for filter UI
                    all_tags = [r["name"] for r in conn.execute(
                        "SELECT DISTINCT t.name FROM tags t "
                        "JOIN note_tags nt ON t.id = nt.tag_id ORDER BY t.name"
                    ).fetchall()]
                    all_sources = [{"id": r["id"], "title": r["title"]} for r in conn.execute(
                        "SELECT id, title FROM sources ORDER BY title"
                    ).fetchall()]

                    self._json_response({
                        "results": results,
                        "tags": all_tags,
                        "sources": all_sources,
                    })
                finally:
                    conn.close()

            elif path == "/api/molecules":
                conn = open_db(brain_dir)
                try:
                    rows = conn.execute(
                        "SELECT slug, eli5, score, method, review_status, body, created_at FROM molecules"
                    ).fetchall()
                    molecules = []
                    for row in rows:
                        molecules.append({
                            "slug": row["slug"],
                            "eli5": row["eli5"],
                            "score": row["score"],
                            "method": row["method"],
                            "review_status": row["review_status"],
                            "body": row["body"],
                            "created_at": row["created_at"],
                        })
                    self._json_response({"molecules": molecules})
                finally:
                    conn.close()

            elif path == "/api/profile":
                conn = open_db(brain_dir)
                try:
                    rows = conn.execute(
                        "SELECT key, value, source, confidence FROM profile"
                    ).fetchall()
                    entries = [
                        {"key": r["key"], "value": r["value"], "source": r["source"], "confidence": r["confidence"]}
                        for r in rows
                    ]
                    self._json_response({"entries": entries})
                finally:
                    conn.close()

            elif path == "/api/activity":
                conn = open_db(brain_dir)
                try:
                    rows = conn.execute(
                        "SELECT type, slug, query, timestamp FROM activity "
                        "ORDER BY timestamp DESC LIMIT 50"
                    ).fetchall()
                    activities = [
                        {"type": r["type"], "slug": r["slug"], "query": r["query"], "timestamp": r["timestamp"]}
                        for r in rows
                    ]
                    self._json_response({"activities": activities})
                finally:
                    conn.close()

            elif path == "/api/reflect":
                from eureka.core.reflect import reflect
                conn = open_db(brain_dir)
                try:
                    result = reflect(conn, brain_dir)
                    self._json_response(result)
                finally:
                    conn.close()

            elif path.startswith("/api/atom/"):
                slug = path[len("/api/atom/"):]
                conn = open_db(brain_dir)
                try:
                    row = conn.execute(
                        "SELECT slug, title, body FROM atoms WHERE slug = ?", (slug,)
                    ).fetchone()
                    if row:
                        tags = [r["name"] for r in conn.execute(
                            "SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id WHERE nt.slug = ?",
                            (slug,),
                        ).fetchall()]
                        self._json_response({
                            "slug": row["slug"],
                            "title": row["title"],
                            "body": row["body"],
                            "tags": tags,
                        })
                    else:
                        self._json_response({"error": "not found"}, 404)
                finally:
                    conn.close()

            elif path == "" or path == "/":
                # Serve dashboard
                dashboard_path = Path(__file__).parent.parent / "dashboard" / "index.html"
                if dashboard_path.exists():
                    html = dashboard_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                else:
                    self._json_response({"error": "dashboard not found"}, 404)

            else:
                self._json_response({"error": "not found"}, 404)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            # POST /api/review/<slug>
            if path.startswith("/api/review/"):
                slug = path[len("/api/review/"):]
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode())
                decision = data.get("decision")

                conn = open_db(brain_dir)
                try:
                    if decision == "yes":
                        accept_molecule(conn, slug, brain_dir)
                        self._json_response({"ok": True, "decision": "accepted"})
                    elif decision == "no":
                        reject_molecule(conn, slug, brain_dir)
                        self._json_response({"ok": True, "decision": "rejected"})
                    elif decision == "skip":
                        # "I already know this" — accept but mark as known
                        from datetime import datetime
                        now = datetime.now().isoformat()
                        conn.execute(
                            "UPDATE molecules SET review_status = 'known', reviewed_at = ? WHERE slug = ?",
                            (now, slug),
                        )
                        conn.execute(
                            "INSERT INTO reviews (slug, decision, reviewed_at) VALUES (?, 'known', ?)",
                            (slug, now),
                        )
                        conn.commit()
                        self._json_response({"ok": True, "decision": "known"})
                    else:
                        self._json_response({"error": "invalid decision"}, 400)
                finally:
                    conn.close()
            else:
                self._json_response({"error": "not found"}, 404)

    def server_factory(port: int) -> HTTPServer:
        server = HTTPServer(("localhost", port), Handler)
        return server

    return {"server_factory": server_factory}
