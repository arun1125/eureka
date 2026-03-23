"""Citation graph — create reference stubs and citation edges from a parsed paper."""

import json
import re
import sqlite3
from eureka.core.db import atom_table, ensure_tag, tag_note


def _slugify(title: str) -> str:
    """Convert title to kebab-case slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:80]  # cap length


def _insert_atom(conn: sqlite3.Connection, tbl: str, slug: str, title: str, body: str, tags: list[str]) -> None:
    """Insert an atom into whichever table the brain uses."""
    if tbl == "notes":
        conn.execute(
            "INSERT INTO notes (slug, type, tags, body, word_count) VALUES (?, 'atom', ?, ?, ?)",
            (slug, json.dumps(tags), body, len(body.split())),
        )
    else:
        conn.execute(
            "INSERT INTO atoms (slug, title, body, body_hash, word_count) VALUES (?, ?, ?, '', ?)",
            (slug, title, body, len(body.split())),
        )


def build_reference_stubs(conn: sqlite3.Connection, references: list[dict],
                          source_atoms: list[str]) -> dict:
    """Create stub atoms for each reference and citation edges.

    Args:
        conn: open DB connection
        references: parsed references from PaperReader
        source_atoms: slugs of atoms extracted from the paper body

    Returns:
        {"stubs_created": int, "edges_created": int}
    """
    _atbl = atom_table(conn)
    stub_tag_id = ensure_tag(conn, "reference-stub")
    paper_tag_id = ensure_tag(conn, "paper")
    stubs_created = 0
    edges_created = 0

    for ref in references:
        title = ref.get("title", "")
        if not title or len(title) < 5:
            continue

        slug = _slugify(title)
        if not slug:
            continue

        # Build body from available metadata
        body_parts = []
        if ref.get("authors"):
            body_parts.append(f"Authors: {', '.join(ref['authors'])}")
        if ref.get("year"):
            body_parts.append(f"Year: {ref['year']}")
        if ref.get("arxiv_id"):
            body_parts.append(f"arXiv: {ref['arxiv_id']}")
        body = "\n".join(body_parts) if body_parts else f"Reference: {ref.get('raw', title)}"

        # Insert stub atom (skip if exists — idempotent)
        existing = conn.execute(f"SELECT slug FROM {_atbl} WHERE slug = ?", (slug,)).fetchone()
        if not existing:
            _insert_atom(conn, _atbl, slug, title, body, ["reference-stub", "paper"])
            tag_note(conn, slug, stub_tag_id)
            tag_note(conn, slug, paper_tag_id)
            stubs_created += 1

            # FTS entry
            conn.execute(
                "INSERT OR IGNORE INTO notes_fts (slug, body, tags) VALUES (?, ?, ?)",
                (slug, body, "reference-stub, paper"),
            )

        # Create citation edges: each source atom → this reference stub
        for source_slug in source_atoms:
            conn.execute(
                "INSERT OR IGNORE INTO edges (source, target) VALUES (?, ?)",
                (source_slug, slug),
            )
            edges_created += 1

    conn.commit()
    return {"stubs_created": stubs_created, "edges_created": edges_created}
