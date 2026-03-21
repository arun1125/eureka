"""eureka discover — find molecule candidates and write top one."""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.discovery import discover_all
from eureka.core.embeddings import _unpack_vector
from eureka.core.output import emit, envelope


def get_llm(brain_dir):
    """Return an LLM instance for molecule writing. Monkeypatch in tests."""
    return None


def _load_embeddings(conn):
    """Load all embeddings from DB, unpacking BLOBs to lists."""
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    return {r["slug"]: _unpack_vector(r["vector"]) for r in rows}


def _slugify(title: str) -> str:
    """Convert a title to a slug."""
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s]+", "-", s)
    return s[:80].strip("-")


def run_discover(brain_dir_path: str, method: str = "all", count: int = 10) -> None:
    brain_dir = Path(brain_dir_path)
    conn = open_db(brain_dir)
    now = datetime.now(timezone.utc).isoformat()

    # Load embeddings
    embeddings = _load_embeddings(conn)

    # Run discovery
    candidates = discover_all(conn, embeddings)[:count]

    # Log discovery run
    conn.execute(
        "INSERT INTO discovery_runs (method, timestamp, candidates_found) VALUES (?, ?, ?)",
        (method, now, len(candidates)),
    )
    conn.commit()

    # If LLM available and candidates found, write top molecule
    llm = get_llm(brain_dir)
    molecules_written = 0

    if llm is not None and candidates:
        top = candidates[0]
        atom_slugs = top["atoms"]
        score = top.get("score", 0)
        method_name = top.get("method", "unknown")

        # Build prompt for molecule writing
        atom_bodies = {}
        for slug in atom_slugs:
            row = conn.execute("SELECT title, body FROM atoms WHERE slug = ?", (slug,)).fetchone()
            if row:
                atom_bodies[slug] = f"# {row['title']}\n\n{row['body']}"

        prompt = (
            "Write a molecule (a synthesis note) connecting these atoms:\n\n"
            + "\n\n---\n\n".join(f"[[{s}]]\n{atom_bodies.get(s, '')}" for s in atom_slugs)
            + "\n\nFormat:\n# <title>\n\n<body with [[wikilinks]]>\n\neli5: <one sentence>\n"
        )

        response = llm.generate(prompt)

        # Parse response
        lines = response.strip().split("\n")
        title = ""
        eli5 = ""
        body_lines = []

        for line in lines:
            if line.startswith("# ") and not title:
                title = line[2:].strip()
            elif line.strip().lower().startswith("eli5:"):
                eli5 = line.split(":", 1)[1].strip()
            else:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()
        slug = _slugify(title) if title else f"molecule-{now}"

        # Store in DB
        conn.execute(
            "INSERT OR REPLACE INTO molecules (slug, title, method, score, review_status, eli5, body, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (slug, title, method_name, score, eli5, body, now),
        )
        for atom_slug in atom_slugs:
            conn.execute(
                "INSERT OR IGNORE INTO molecule_atoms (molecule_slug, atom_slug) VALUES (?, ?)",
                (slug, atom_slug),
            )
        conn.commit()

        # Write .md file
        mol_dir = brain_dir / "molecules"
        mol_dir.mkdir(parents=True, exist_ok=True)
        md_path = mol_dir / f"{slug}.md"
        md_path.write_text(response.strip() + "\n")

        molecules_written = 1

    conn.close()

    emit(envelope(True, "discover", {
        "candidates_found": len(candidates),
        "molecules_written": molecules_written,
        "method": method,
    }))
