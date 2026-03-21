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
                    # Build adjacency for simple community detection
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

                    # Simple community: assign by connected component
                    adj = {s: set() for s in all_slugs}
                    edge_list = []
                    for row in conn.execute("SELECT source, target, similarity FROM edges"):
                        s, t = row["source"], row["target"]
                        if s in adj and t in adj:
                            adj[s].add(t)
                            adj[t].add(s)
                        edge_list.append({"source": s, "target": t, "similarity": row["similarity"]})

                    community = {}
                    c = 0
                    visited = set()
                    for node in all_slugs:
                        if node in visited:
                            continue
                        queue = [node]
                        while queue:
                            n = queue.pop()
                            if n in visited:
                                continue
                            visited.add(n)
                            community[n] = c
                            for nb in adj.get(n, set()):
                                if nb not in visited:
                                    queue.append(nb)
                        c += 1

                    nodes = []
                    for slug in all_slugs:
                        node = {
                            "slug": slug,
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
                conn = open_db(brain_dir)
                try:
                    results = []
                    if q:
                        rows = conn.execute(
                            "SELECT slug, snippet(notes_fts) as snippet FROM notes_fts WHERE body MATCH ?",
                            (q,),
                        ).fetchall()
                        for row in rows:
                            results.append({
                                "slug": row["slug"],
                                "snippet": row["snippet"],
                            })
                    self._json_response({"results": results})
                finally:
                    conn.close()

            elif path == "/api/molecules":
                conn = open_db(brain_dir)
                try:
                    rows = conn.execute(
                        "SELECT slug, eli5, score, method, review_status, body FROM molecules"
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
                        })
                    self._json_response({"molecules": molecules})
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
