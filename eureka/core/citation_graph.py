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


def enrich_stubs(conn: sqlite3.Connection, references: list[dict],
                 progress_callback=None) -> dict:
    """Enrich reference stubs with Semantic Scholar abstracts and metadata.

    Finds existing stubs (tagged 'reference-stub'), enriches via S2 API,
    updates body with abstract, returns counts.
    """
    from eureka.core.semantic_scholar import enrich_all_references

    _atbl = atom_table(conn)

    # Get all reference-stub slugs
    stub_tag = conn.execute("SELECT id FROM tags WHERE name = 'reference-stub'").fetchone()
    if not stub_tag:
        return {"enriched": 0, "not_found": 0, "already_enriched": 0}

    stubs = conn.execute(
        f"SELECT n.slug, n.body FROM {_atbl} n "
        f"INNER JOIN note_tags nt ON nt.slug = n.slug "
        f"WHERE nt.tag_id = ?",
        (stub_tag["id"],),
    ).fetchall()

    # Skip stubs that already have an abstract (body > 200 chars = likely enriched)
    to_enrich = []
    already_enriched = 0
    for stub in stubs:
        if len(stub["body"] or "") > 200:
            already_enriched += 1
        else:
            to_enrich.append(stub)

    if not to_enrich:
        return {"enriched": 0, "not_found": 0, "already_enriched": already_enriched}

    # Build reference list from stubs for S2 lookup
    refs_for_s2 = []
    for stub in to_enrich:
        # Extract arxiv_id from body if present
        arxiv_id = None
        body = stub["body"] or ""
        for line in body.split("\n"):
            if line.startswith("arXiv:"):
                arxiv_id = line.split(":", 1)[1].strip()
        # Title from slug
        title = stub["slug"].replace("-", " ")
        refs_for_s2.append({"title": title, "arxiv_id": arxiv_id, "slug": stub["slug"]})

    enriched_data = enrich_all_references(refs_for_s2, progress_callback=progress_callback)

    enriched_count = 0
    not_found = 0
    for ref_data, stub_info in zip(enriched_data, refs_for_s2):
        if not ref_data.get("enriched"):
            not_found += 1
            continue

        # Build enriched body
        parts = []
        if ref_data.get("abstract"):
            parts.append(ref_data["abstract"])
        if ref_data.get("authors"):
            parts.append(f"\nAuthors: {', '.join(ref_data['authors'])}")
        if ref_data.get("year"):
            parts.append(f"Year: {ref_data['year']}")
        if ref_data.get("citation_count"):
            parts.append(f"Citations: {ref_data['citation_count']}")
        if ref_data.get("tldr"):
            parts.append(f"\nTLDR: {ref_data['tldr']}")
        if ref_data.get("doi"):
            parts.append(f"DOI: {ref_data['doi']}")
        if ref_data.get("arxiv_id"):
            parts.append(f"arXiv: {ref_data['arxiv_id']}")

        new_body = "\n".join(parts)
        slug = stub_info["slug"]

        conn.execute(f"UPDATE {_atbl} SET body = ? WHERE slug = ?", (new_body, slug))
        # Update FTS
        conn.execute("DELETE FROM notes_fts WHERE slug = ?", (slug,))
        conn.execute(
            "INSERT INTO notes_fts (slug, body, tags) VALUES (?, ?, ?)",
            (slug, new_body, "reference-stub, paper"),
        )
        enriched_count += 1

    conn.commit()
    return {"enriched": enriched_count, "not_found": not_found, "already_enriched": already_enriched}
