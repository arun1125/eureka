"""Index — sync .md files into the database."""

import sqlite3
from pathlib import Path

from eureka.core.db import ensure_tag, tag_note
from eureka.core.parser import parse_note


def rebuild_index(conn: sqlite3.Connection, brain_dir: Path) -> None:
    """Glob all .md files in brain_dir/atoms/, parse and upsert into DB."""
    atoms_dir = brain_dir / "atoms"
    if not atoms_dir.is_dir():
        return

    # Parse all atoms first so we know which slugs exist
    notes = []
    for md_path in sorted(atoms_dir.glob("*.md")):
        notes.append(parse_note(md_path))

    slug_set = {n["slug"] for n in notes}

    # Clear edges, note_tags, and FTS before rebuild (idempotent)
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM note_tags")
    conn.execute("DELETE FROM notes_fts")

    for note in notes:
        word_count = len(note["body"].split())

        # Upsert atom
        conn.execute(
            """INSERT OR REPLACE INTO atoms
               (slug, title, body, body_hash, word_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (note["slug"], note["title"], note["body"], note["body_hash"], word_count),
        )

        # Insert edges — only if target exists as an atom
        for wikilink in note["wikilinks"]:
            if wikilink in slug_set:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source, target, created_at) VALUES (?, ?, datetime('now'))",
                    (note["slug"], wikilink),
                )

        # Tags
        for tag_name in note["tags"]:
            tag_id = ensure_tag(conn, tag_name)
            tag_note(conn, note["slug"], tag_id)

        # FTS
        tags_str = ", ".join(note["tags"])
        conn.execute(
            "INSERT INTO notes_fts (slug, body, tags) VALUES (?, ?, ?)",
            (note["slug"], note["body"], tags_str),
        )

    conn.commit()
