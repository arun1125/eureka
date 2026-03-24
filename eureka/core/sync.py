"""Sync — keep brain.db in sync with .md files on disk."""

import hashlib
import sqlite3
import sys
from pathlib import Path

from eureka.core.db import atom_table, log_operation
from eureka.core.parser import parse_note


def scan_files(brain_dir: Path) -> dict:
    """Walk atoms/ and molecules/ directories, return {slug: {path, hash, type}}."""
    result = {}
    atoms_dir = brain_dir / "atoms"
    if atoms_dir.is_dir():
        for md in atoms_dir.glob("*.md"):
            slug = md.stem
            file_hash = hashlib.sha256(md.read_bytes()).hexdigest()
            result[slug] = {"path": md, "hash": file_hash, "type": "atom"}

    mol_dir = brain_dir / "molecules"
    if mol_dir.is_dir():
        for md in mol_dir.glob("*.md"):
            slug = md.stem
            file_hash = hashlib.sha256(md.read_bytes()).hexdigest()
            result[slug] = {"path": md, "hash": file_hash, "type": "molecule"}

    return result


def scan_db(conn: sqlite3.Connection) -> dict:
    """Query atoms and molecules tables, return {slug: {file_hash, type}}."""
    result = {}
    _atbl = atom_table(conn)

    for r in conn.execute(f"SELECT slug, file_hash FROM {_atbl}").fetchall():
        result[r["slug"]] = {"file_hash": r["file_hash"], "type": "atom"}

    for r in conn.execute("SELECT slug, file_hash FROM molecules").fetchall():
        result[r["slug"]] = {"file_hash": r["file_hash"], "type": "molecule"}

    return result


def compute_diff(file_state: dict, db_state: dict) -> dict:
    """Compare file and DB state, return sync plan."""
    file_only = []
    db_only = []
    changed = []
    in_sync = 0

    for slug, finfo in file_state.items():
        if slug not in db_state:
            file_only.append({"slug": slug, **finfo})
        elif finfo["hash"] != db_state[slug]["file_hash"]:
            changed.append({"slug": slug, **finfo})
        else:
            in_sync += 1

    for slug, dinfo in db_state.items():
        if slug not in file_state:
            db_only.append({"slug": slug, **dinfo})

    return {
        "add": file_only,
        "remove": db_only,
        "update": changed,
        "in_sync": in_sync,
    }


def _cascade_delete(conn: sqlite3.Connection, slug: str, item_type: str) -> None:
    """Delete a slug and all its references from the DB."""
    if item_type == "atom":
        conn.execute("DELETE FROM edges WHERE source = ? OR target = ?", (slug, slug))
        conn.execute("DELETE FROM note_tags WHERE slug = ?", (slug,))
        conn.execute("DELETE FROM embeddings WHERE slug = ?", (slug,))
        conn.execute("DELETE FROM molecule_atoms WHERE atom_slug = ?", (slug,))
        conn.execute("DELETE FROM notes_fts WHERE slug = ?", (slug,))
        _atbl = atom_table(conn)
        conn.execute(f"DELETE FROM {_atbl} WHERE slug = ?", (slug,))
    elif item_type == "molecule":
        conn.execute("DELETE FROM molecule_atoms WHERE molecule_slug = ?", (slug,))
        conn.execute("DELETE FROM molecules WHERE slug = ?", (slug,))


def apply_sync(conn: sqlite3.Connection, brain_dir: Path, plan: dict,
               dry_run: bool = False) -> dict:
    """Apply a sync plan. Returns summary of actions taken."""
    added = 0
    removed = 0
    updated = 0

    if dry_run:
        return {
            "dry_run": True,
            "would_add": len(plan["add"]),
            "would_remove": len(plan["remove"]),
            "would_update": len(plan["update"]),
            "in_sync": plan["in_sync"],
            "add": [i["slug"] for i in plan["add"]],
            "remove": [i["slug"] for i in plan["remove"]],
            "update": [i["slug"] for i in plan["update"]],
        }

    # Add: files exist but not in DB
    _atbl = atom_table(conn)
    for item in plan["add"]:
        slug = item["slug"]
        if item["type"] == "atom":
            note = parse_note(item["path"])
            word_count = len(note["body"].split())
            conn.execute(
                f"""INSERT OR IGNORE INTO {_atbl}
                    (slug, title, body, body_hash, word_count, file_hash, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                (slug, note["title"], note["body"], note["body_hash"],
                 word_count, item["hash"]),
            )
            added += 1
        elif item["type"] == "molecule":
            content = item["path"].read_text()
            conn.execute(
                "INSERT OR IGNORE INTO molecules (slug, body, file_hash, created_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                (slug, content, item["hash"]),
            )
            added += 1

    # Remove: in DB but no file
    for item in plan["remove"]:
        _cascade_delete(conn, item["slug"], item["type"])
        removed += 1

    # Update: file changed
    for item in plan["update"]:
        slug = item["slug"]
        if item["type"] == "atom":
            note = parse_note(item["path"])
            word_count = len(note["body"].split())
            conn.execute(
                f"""UPDATE {_atbl} SET title=?, body=?, body_hash=?,
                    word_count=?, file_hash=?, updated_at=datetime('now')
                    WHERE slug=?""",
                (note["title"], note["body"], note["body_hash"],
                 word_count, item["hash"], slug),
            )
            # Clear embedding so it gets re-embedded
            conn.execute("DELETE FROM embeddings WHERE slug = ?", (slug,))
            updated += 1
        elif item["type"] == "molecule":
            content = item["path"].read_text()
            conn.execute(
                "UPDATE molecules SET body=?, file_hash=? WHERE slug=?",
                (content, item["hash"], slug),
            )
            updated += 1

    conn.commit()

    # Re-embed and re-link if atoms were touched
    if added > 0 or updated > 0:
        from eureka.core.embeddings import ensure_embeddings
        from eureka.core.linker import link_all
        print("Re-embedding and re-linking...", file=sys.stderr, flush=True)
        ensure_embeddings(conn, brain_dir)
        link_all(conn)

    log_operation(conn, "sync", detail={
        "added": added, "removed": removed, "updated": updated,
        "in_sync": plan["in_sync"],
    })
    conn.commit()

    return {
        "added": added,
        "removed": removed,
        "updated": updated,
        "in_sync": plan["in_sync"],
    }


def run_sync(conn: sqlite3.Connection, brain_dir: Path,
             dry_run: bool = False) -> dict:
    """Full sync: scan files, scan DB, compute diff, apply."""
    file_state = scan_files(brain_dir)
    db_state = scan_db(conn)
    plan = compute_diff(file_state, db_state)
    return apply_sync(conn, brain_dir, plan, dry_run=dry_run)
