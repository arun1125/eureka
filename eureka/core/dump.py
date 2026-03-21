"""Dump — extract atoms from raw freeform text (brain dumps)."""

import struct
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.extractor import parse_extraction_response
from eureka.core.embeddings import embed_text, cosine_sim, _unpack_vector
from eureka.core.index import rebuild_index
from eureka.core.embeddings import ensure_embeddings
from eureka.core.linker import link_all
from eureka.core.activity import log_activity
from eureka.core.pushback import find_contradictions, find_gaps
from eureka.core.profile import get_relevant_profile


def _build_dump_prompt(raw_text: str, existing_tags: list[str]) -> str:
    """Build an extraction prompt tuned for personal brain dumps."""
    return f"""You are helping someone process a personal brain dump.
Extract the key ideas as atomic concepts. Each concept should be a single
independent insight — personal, opinionated, and honest.

For each concept, output:
- A title as an H1 heading (# Title) — write it as a claim, not a topic
- A body paragraph explaining the idea in the person's own voice
- A tags line with comma-separated tags

Reuse existing tags where appropriate: {', '.join(existing_tags)}

Separate each atom with --- on its own line.

Brain dump:
{raw_text}"""


def process_dump(raw_text: str, conn: sqlite3.Connection, brain_dir: Path, llm) -> dict:
    """Extract atoms from raw text, connect to existing brain.

    Returns dict with keys: atoms_extracted, connections, molecules_touched
    """
    # Get existing tags for prompt
    existing_tags = [r["name"] for r in conn.execute("SELECT name FROM tags").fetchall()]

    # Build prompt and call LLM
    prompt = _build_dump_prompt(raw_text, existing_tags)
    response = llm.generate(prompt)

    # Parse extraction response
    atoms = parse_extraction_response(response)

    # Write atom .md files
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(exist_ok=True)
    for atom in atoms:
        md = f"# {atom['title']}\n\n{atom['body']}\n\ntags: {', '.join(atom['tags'])}\n"
        (atoms_dir / f"{atom['slug']}.md").write_text(md)

    # Re-index to pick up new atoms
    rebuild_index(conn, brain_dir)

    # Embed new atoms
    ensure_embeddings(conn, brain_dir)

    # Link all atoms (creates edges based on cosine similarity)
    link_all(conn)

    # Find connections: for each new atom, find nearest existing atoms
    connections = []
    new_slugs = {a["slug"] for a in atoms}

    # Load all embeddings
    emb_rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    vectors = {}
    for r in emb_rows:
        vectors[r["slug"]] = _unpack_vector(r["vector"])

    for atom in atoms:
        slug = atom["slug"]
        if slug not in vectors:
            continue
        vec = vectors[slug]
        for other_slug, other_vec in vectors.items():
            if other_slug in new_slugs:
                continue
            sim = cosine_sim(vec, other_vec)
            if sim > 0.3:
                connections.append({
                    "new_atom": slug,
                    "existing_atom": other_slug,
                    "similarity": round(sim, 4),
                })

    # Sort connections by similarity descending
    connections.sort(key=lambda c: c["similarity"], reverse=True)

    # Find molecules that contain connected existing atoms
    connected_existing = {c["existing_atom"] for c in connections}
    molecules_touched = []
    if connected_existing:
        placeholders = ",".join("?" * len(connected_existing))
        mol_rows = conn.execute(
            f"""SELECT DISTINCT m.slug, m.title
                FROM molecules m
                JOIN molecule_atoms ma ON m.slug = ma.molecule_slug
                WHERE ma.atom_slug IN ({placeholders})""",
            list(connected_existing),
        ).fetchall()
        molecules_touched = [{"slug": r["slug"], "title": r["title"]} for r in mol_rows]

    # Create source row
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO sources (title, type, ingested_at, atom_count, raw_text) VALUES (?, ?, ?, ?, ?)",
        (f"dump-{now[:10]}", "dump", now, len(atoms), raw_text),
    )
    conn.commit()

    # Pushback: detect contradictions and gaps
    new_embeddings = {}
    for atom in atoms:
        slug = atom["slug"]
        if slug in vectors:
            new_embeddings[slug] = vectors[slug]

    existing_embeddings = {s: v for s, v in vectors.items() if s not in new_slugs}
    tensions = find_contradictions(new_embeddings, existing_embeddings, conn)
    gaps = find_gaps(new_embeddings, existing_embeddings, conn)

    # Profile context — find relevant profile entries near the dump
    dump_vec = embed_text(raw_text)
    profile_entries = get_relevant_profile(conn, vectors, dump_vec)
    profile_context = [{"key": e["key"], "value": e["value"]} for e in profile_entries]

    # Log activity
    log_activity(conn, "dump")

    return {
        "atoms_extracted": atoms,
        "connections": connections,
        "molecules_touched": molecules_touched,
        "tensions": tensions,
        "gaps": gaps,
        "profile_context": profile_context,
    }
