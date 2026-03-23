"""HTTP API server for the Eureka dashboard."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from eureka.core.db import open_db, get_stats, atom_table, atom_title_expr, atom_source_expr
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

        def _text_search(self, conn, q, _atbl, _title_expr, source_id, _src_expr):
            """Text-based search fallback (LIKE query)."""
            where_clauses = []
            params = []
            if source_id:
                src_row = conn.execute("SELECT title FROM sources WHERE id = ?", (source_id,)).fetchone()
                if src_row:
                    where_clauses.append(f"{_src_expr} = ?")
                    params.append(src_row["title"])
            if q and q.strip():
                where_clauses.append(f"({_title_expr} LIKE ? OR body LIKE ? OR slug LIKE ?)")
                params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
            sql = f"SELECT slug, {_title_expr} AS title, body FROM {_atbl}"
            if where_clauses:
                sql += " WHERE " + " AND ".join(where_clauses)
            sql += f" ORDER BY {_title_expr} LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
            return [{"slug": r["slug"], "title": r["title"], "snippet": (r["body"] or "")[:200]} for r in rows]

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
                    _atbl = atom_table(conn)
                    for row in conn.execute(f"SELECT slug FROM {_atbl}"):
                        all_slugs.append(row["slug"])
                        slug_type[row["slug"]] = "atom"
                    for row in conn.execute("SELECT slug, method FROM molecules"):
                        all_slugs.append(row["slug"])
                        slug_type[row["slug"]] = "molecule"
                        slug_method[row["slug"]] = row["method"]
                    atom_set = set(all_slugs)

                    # Collect atom-atom edges (top 5 per atom for graph clarity)
                    from collections import defaultdict
                    edge_counts = defaultdict(int)
                    edge_list = []
                    for row in conn.execute("SELECT source, target, similarity FROM edges ORDER BY COALESCE(similarity, 1.0) DESC"):
                        s, t = row["source"], row["target"]
                        sim = row["similarity"] if row["similarity"] is not None else 1.0
                        if s in atom_set and t in atom_set:
                            if edge_counts[s] < 5 and edge_counts[t] < 5:
                                edge_list.append({"source": s, "target": t, "similarity": sim})
                                edge_counts[s] += 1
                                edge_counts[t] += 1

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
                    _title_expr = atom_title_expr(conn)
                    for row in conn.execute(f"SELECT slug, {_title_expr} AS title FROM {_atbl}"):
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
                source_id = qs.get("source", [""])[0]
                conn = open_db(brain_dir)
                try:
                    _atbl = atom_table(conn)
                    _title_expr = atom_title_expr(conn)
                    _src_expr = atom_source_expr(conn)

                    # Semantic search: embed query and rank by cosine similarity
                    results = []
                    if q and q.strip():
                        from eureka.core.embeddings import embed_text, cosine_sim, _unpack_vector
                        query_vec = embed_text(q)

                        if query_vec is not None:
                            # Load all embeddings
                            emb_rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
                            scored = []
                            for r in emb_rows:
                                vec = _unpack_vector(r["vector"])
                                sim = cosine_sim(query_vec, vec)
                                scored.append((r["slug"], sim))
                            scored.sort(key=lambda x: x[1], reverse=True)

                            # Optional source filter
                            source_filter = None
                            if source_id:
                                src_row = conn.execute(
                                    "SELECT title FROM sources WHERE id = ?", (source_id,)
                                ).fetchone()
                                if src_row:
                                    source_filter = src_row["title"]

                            for slug, sim in scored[:100]:
                                row = conn.execute(
                                    f"SELECT slug, {_title_expr} AS title, body, {_src_expr} AS src FROM {_atbl} WHERE slug = ?",
                                    (slug,),
                                ).fetchone()
                                if not row:
                                    continue
                                if source_filter and row["src"] != source_filter:
                                    continue
                                results.append({
                                    "slug": row["slug"],
                                    "title": row["title"],
                                    "snippet": (row["body"] or "")[:200],
                                    "similarity": round(sim, 4),
                                })
                        else:
                            # Fallback to text search if embedding fails
                            results = self._text_search(conn, q, _atbl, _title_expr, source_id, _src_expr)
                    else:
                        # No query — return all atoms (for browsing)
                        results = self._text_search(conn, "", _atbl, _title_expr, source_id, _src_expr)

                    # Sources for dropdown
                    all_sources = [{"id": r["id"], "title": r["title"]} for r in conn.execute(
                        "SELECT id, title FROM sources ORDER BY title"
                    ).fetchall()]

                    self._json_response({
                        "results": results,
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
                    # Check atoms first
                    _atbl = atom_table(conn)
                    _title_expr = atom_title_expr(conn)
                    row = conn.execute(
                        f"SELECT slug, {_title_expr} AS title, body FROM {_atbl} WHERE slug = ?", (slug,)
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
                            "type": "atom",
                        })
                    else:
                        # Check molecules
                        mol = conn.execute(
                            "SELECT slug, title, eli5, body, method, score FROM molecules WHERE slug = ?", (slug,)
                        ).fetchone()
                        if mol:
                            atoms = [r["atom_slug"] for r in conn.execute(
                                "SELECT atom_slug FROM molecule_atoms WHERE molecule_slug = ?", (slug,)
                            ).fetchall()]
                            self._json_response({
                                "slug": mol["slug"],
                                "title": mol["title"],
                                "body": mol["body"] or "",
                                "eli5": mol["eli5"] or "",
                                "method": mol["method"],
                                "score": mol["score"],
                                "tags": [mol["method"]] if mol["method"] else [],
                                "atoms": atoms,
                                "type": "molecule",
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

            elif path == "/api/neighbors":
                qs = parse_qs(parsed.query)
                atom_slug = qs.get("atom", [""])[0]
                exclude = qs.get("exclude", [""])[0]
                exclude_set = set(exclude.split(",")) if exclude else set()
                limit = int(qs.get("limit", ["6"])[0])

                if not atom_slug:
                    self._json_response({"error": "atom parameter required"}, 400)
                    return

                conn = open_db(brain_dir)
                try:
                    import numpy as np
                    from eureka.core.embeddings import _unpack_vector

                    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
                    embeddings = {r["slug"]: _unpack_vector(r["vector"]) for r in rows}

                    if atom_slug not in embeddings:
                        self._json_response({"error": "atom not found"}, 404)
                        return

                    # Compute similarities to all other atoms
                    start_vec = np.array(embeddings[atom_slug], dtype=np.float32)
                    start_vec = start_vec / (np.linalg.norm(start_vec) or 1.0)

                    scored = []
                    for slug, vec in embeddings.items():
                        if slug == atom_slug or slug in exclude_set:
                            continue
                        v = np.array(vec, dtype=np.float32)
                        v = v / (np.linalg.norm(v) or 1.0)
                        sim = float(np.dot(start_vec, v))
                        scored.append((slug, sim))

                    scored.sort(key=lambda x: x[1], reverse=True)
                    top = scored[:limit]

                    _atbl = atom_table(conn)
                    _title_expr = atom_title_expr(conn)
                    neighbors = []
                    for slug, sim in top:
                        row = conn.execute(f"SELECT {_title_expr} AS title FROM {_atbl} WHERE slug = ?", (slug,)).fetchone()
                        neighbors.append({
                            "slug": slug,
                            "title": row["title"] if row else slug.replace("-", " "),
                            "similarity": round(sim, 4),
                        })

                    self._json_response({"neighbors": neighbors})
                finally:
                    conn.close()

            elif path == "/api/discover/from":
                qs = parse_qs(parsed.query)
                atom_slug = qs.get("atom", [""])[0]
                method = qs.get("method", ["walk"])[0]

                if not atom_slug:
                    self._json_response({"error": "atom parameter required"}, 400)
                    return

                conn = open_db(brain_dir)
                try:
                    from eureka.core.embeddings import _unpack_vector
                    from eureka.core.discovery import discover_from_atom
                    from eureka.core.scorer import score_candidate

                    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
                    embeddings = {r["slug"]: _unpack_vector(r["vector"]) for r in rows}

                    candidates = discover_from_atom(conn, embeddings, atom_slug, method, cap=10)

                    # Score each candidate
                    _atbl = atom_table(conn)
                    _title_expr = atom_title_expr(conn)
                    _src_expr = atom_source_expr(conn)
                    source_map = {}
                    try:
                        for r in conn.execute(f"SELECT slug, {_src_expr} AS source_title FROM {_atbl} WHERE {_src_expr} IS NOT NULL"):
                            source_map[r["slug"]] = r["source_title"]
                    except Exception:
                        pass

                    for c in candidates:
                        atom_slugs = c["atoms"]
                        emb = {s: embeddings[s] for s in atom_slugs if s in embeddings}
                        c["score"] = score_candidate(atom_slugs, emb, embeddings, source_map)

                    # Add titles
                    for c in candidates:
                        c["atom_titles"] = {}
                        for s in c["atoms"]:
                            row = conn.execute(f"SELECT {_title_expr} AS title FROM {_atbl} WHERE slug = ?", (s,)).fetchone()
                            c["atom_titles"][s] = row["title"] if row else s.replace("-", " ")

                    candidates.sort(key=lambda c: c.get("score", 0), reverse=True)
                    self._json_response({"candidates": candidates})
                finally:
                    conn.close()

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
            elif path == "/api/generate-molecule":
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode())
                atom_slugs = data.get("atoms", [])

                if len(atom_slugs) < 2:
                    self._json_response({"error": "need at least 2 atoms"}, 400)
                    return

                conn = open_db(brain_dir)
                try:
                    import re
                    from eureka.core.llm import get_llm
                    from datetime import datetime, timezone

                    from eureka.core.llm import load_llm_config
                    llm = get_llm(config=load_llm_config(brain_dir))
                    if llm is None:
                        self._json_response({"error": "no LLM configured (set ANTHROPIC_API_KEY or configure brain.json)"}, 500)
                        return

                    # Build prompt
                    _atbl = atom_table(conn)
                    _title_expr = atom_title_expr(conn)
                    atom_bodies = {}
                    for slug in atom_slugs:
                        row = conn.execute(f"SELECT {_title_expr} AS title, body FROM {_atbl} WHERE slug = ?", (slug,)).fetchone()
                        if row:
                            atom_bodies[slug] = f"# {row['title']}\n\n{row['body']}"

                    prompt = (
                        "Write a molecule — a synthesis note that connects these atoms into a single insight none of them state alone.\n\n"
                        "Here are the atoms:\n\n"
                        + "\n\n---\n\n".join(f"[[{s}]]\n{atom_bodies.get(s, '')}" for s in atom_slugs)
                        + "\n\n---\n\n"
                        "Write the molecule in EXACTLY this format (no deviations):\n\n"
                        "```\n"
                        "# Title as a short opinionated claim (under 80 chars)\n"
                        "\n"
                        "First paragraph: weave the atoms together, explaining WHY these ideas connect. "
                        "Use [[wikilinks]] to reference atoms naturally in the flow. Write like an essay, not a list.\n"
                        "\n"
                        "Second paragraph: extract the higher-order principle — the thing you can only see once all atoms are in view. "
                        "Be specific and actionable.\n"
                        "\n"
                        "eli5: One vivid sentence a 10-year-old would understand. Use a concrete metaphor.\n"
                        "```\n\n"
                        "Rules:\n"
                        "- Title must be a SHORT claim (under 80 chars). No wikilinks in the title.\n"
                        "- Body should be 2 paragraphs, 4-8 sentences total.\n"
                        "- Do NOT just summarize the atoms — synthesize them into something new.\n"
                    )

                    response = llm.generate(prompt)

                    # Parse response
                    raw = response.strip()
                    raw = re.sub(r"^```\w*\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw)
                    lines = raw.strip().split("\n")
                    title = ""
                    eli5 = ""
                    body_lines = []
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("```"):
                            continue
                        if line.startswith("# ") and not title:
                            title = line[2:].strip()
                        elif stripped.lower().startswith("eli5:"):
                            eli5 = line.split(":", 1)[1].strip()
                        else:
                            body_lines.append(line)
                    mol_body = "\n".join(body_lines).strip()

                    # Slugify
                    slug = title.lower().strip()
                    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
                    slug = re.sub(r"[\s]+", "-", slug)[:80].strip("-")

                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT OR REPLACE INTO molecules (slug, title, method, score, review_status, eli5, body, created_at) "
                        "VALUES (?, ?, 'manual', 0, 'pending', ?, ?, ?)",
                        (slug, title, eli5, mol_body, now),
                    )
                    for atom_slug in atom_slugs:
                        conn.execute(
                            "INSERT OR IGNORE INTO molecule_atoms (molecule_slug, atom_slug) VALUES (?, ?)",
                            (slug, atom_slug),
                        )
                    conn.commit()

                    self._json_response({
                        "ok": True,
                        "molecule": {
                            "slug": slug, "title": title, "body": mol_body,
                            "eli5": eli5, "atoms": atom_slugs,
                        }
                    })
                except Exception as e:
                    self._json_response({"error": str(e)}, 500)
                finally:
                    conn.close()

            else:
                self._json_response({"error": "not found"}, 404)

    def server_factory(port: int) -> HTTPServer:
        server = HTTPServer(("localhost", port), Handler)
        return server

    return {"server_factory": server_factory}
