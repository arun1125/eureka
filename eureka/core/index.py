"""Index — sync .md files into the database."""

import hashlib
import json
import sqlite3
from pathlib import Path

from eureka.core.db import atom_table, ensure_tag, tag_note
from eureka.core.parser import parse_note


def rebuild_index(conn: sqlite3.Connection, brain_dir: Path) -> None:
    """Glob all .md files in brain_dir/atoms/, parse and upsert into DB.

    Writes to whichever table the brain uses (atoms or notes).
    Preserves source_id and other lineage columns on existing atoms.
    """
    atoms_dir = brain_dir / "atoms"
    if not atoms_dir.is_dir():
        return

    _atbl = atom_table(conn)

    # Parse all atoms first so we know which slugs exist
    notes = []
    for md_path in sorted(atoms_dir.glob("*.md")):
        note = parse_note(md_path)
        note["file_hash"] = hashlib.sha256(md_path.read_bytes()).hexdigest()
        notes.append(note)

    slug_set = {n["slug"] for n in notes}

    # Get existing slugs so we can UPDATE instead of INSERT OR REPLACE
    existing_slugs = {
        r[0] for r in conn.execute(f"SELECT slug FROM {_atbl}").fetchall()
    }

    # Clear edges, note_tags, and FTS before rebuild (idempotent)
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM note_tags")
    conn.execute("DELETE FROM notes_fts")

    for note in notes:
        word_count = len(note["body"].split())

        if note["slug"] in existing_slugs:
            # UPDATE existing atom — preserves source_id and created_at
            if _atbl == "notes":
                conn.execute(
                    """UPDATE notes SET type='atom', tags=?, body=?,
                       word_count=?, mtime=datetime('now') WHERE slug=?""",
                    (json.dumps(note["tags"]), note["body"], word_count, note["slug"]),
                )
            else:
                conn.execute(
                    """UPDATE atoms SET title=?, body=?, body_hash=?,
                       word_count=?, file_hash=?, updated_at=datetime('now')
                       WHERE slug=?""",
                    (note["title"], note["body"], note["body_hash"],
                     word_count, note["file_hash"], note["slug"]),
                )
        else:
            # INSERT new atom
            if _atbl == "notes":
                conn.execute(
                    """INSERT INTO notes
                       (slug, type, tags, body, word_count, mtime)
                       VALUES (?, 'atom', ?, ?, ?, datetime('now'))""",
                    (note["slug"], json.dumps(note["tags"]), note["body"], word_count),
                )
            else:
                conn.execute(
                    """INSERT INTO atoms
                       (slug, title, body, body_hash, word_count, file_hash, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                    (note["slug"], note["title"], note["body"], note["body_hash"],
                     word_count, note["file_hash"]),
                )

        # Insert edges — only if target exists as an atom
        for wikilink in note["wikilinks"]:
            if wikilink in slug_set:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (source, target, created_at) VALUES (?, ?, datetime('now'))",
                    (note["slug"], wikilink),
                )

        # Tags — always populate normalized tables
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
