"""Sync — keep brain.db in sync with .md files on disk."""

import hashlib
import sqlite3
import sys
from pathlib import Path

from eureka.core.db import atom_table, log_operation
from eureka.core.parser import parse_note


def scan_files(brain_dir: Path) -> dict:
    """Walk atoms/ and molecules/ directories, return {slug: {path, hash, type}}.

    Supports both Eureka layout (atoms/, molecules/) and SecondBrainKit layout
    (*.md at root level). If atoms/ exists and has files, use it. Otherwise fall
    back to root-level .md files as atoms.
    """
    result = {}

    # Atoms: scan both atoms/ subdir and root-level .md files, merge.
    # Eureka uses atoms/; SecondBrainKit puts .md at root. Support both.
    atoms_dir = brain_dir / "atoms"
    _exclude = {"brain.json", "README.md", "CHANGELOG.md"}
    seen_slugs = set()

    atom_files = []
    if atoms_dir.is_dir():
        atom_files.extend(atoms_dir.glob("*.md"))
    # Also scan root-level .md (SecondBrainKit layout)
    atom_files.extend(
        md for md in brain_dir.glob("*.md")
        if md.name not in _exclude
    )

    for md in atom_files:
        slug = md.stem
        if slug in seen_slugs:
            continue  # atoms/ version takes precedence (listed first)
        seen_slugs.add(slug)
        slug = md.stem
        file_hash = hashlib.sha256(md.read_bytes()).hexdigest()
        result[slug] = {"path": md, "hash": file_hash, "type": "atom"}

    # Molecules
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
    _use_notes = (_atbl == "notes")
    for item in plan["add"]:
        slug = item["slug"]
        if item["type"] == "atom":
            note = parse_note(item["path"])
            word_count = len(note["body"].split())
            if _use_notes:
                # SecondBrainKit schema: notes table
                tags_str = ", ".join(note.get("tags", []))
                conn.execute(
                    """INSERT OR IGNORE INTO notes
                        (slug, type, body, tags, word_count, file_hash, mtime)
                        VALUES (?, 'atom', ?, ?, ?, ?, datetime('now'))""",
                    (slug, note["body"], tags_str, word_count, item["hash"]),
                )
            else:
                # Eureka schema: atoms table
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
            if _use_notes:
                tags_str = ", ".join(note.get("tags", []))
                conn.execute(
                    """UPDATE notes SET body=?, tags=?,
                        word_count=?, file_hash=?, mtime=datetime('now')
                        WHERE slug=?""",
                    (note["body"], tags_str, word_count, item["hash"], slug),
                )
            else:
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


def _backfill_hashes(conn: sqlite3.Connection, brain_dir: Path) -> int:
    """Backfill file_hash for DB rows that have NULL hashes (imported brains).

    Matches DB slugs to files on disk and stamps the hash. Returns count updated.
    """
    _atbl = atom_table(conn)
    count = 0

    # Backfill atoms/notes — check atoms/ subdir then root
    null_atoms = conn.execute(f"SELECT slug FROM {_atbl} WHERE file_hash IS NULL").fetchall()
    if null_atoms:
        atoms_dir = brain_dir / "atoms"
        for row in null_atoms:
            slug = row["slug"]
            md_path = atoms_dir / f"{slug}.md"
            if not md_path.exists():
                md_path = brain_dir / f"{slug}.md"  # SecondBrainKit layout
            if md_path.exists():
                file_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
                conn.execute(f"UPDATE {_atbl} SET file_hash = ? WHERE slug = ?", (file_hash, slug))
                count += 1

    # Backfill molecules
    null_mols = conn.execute("SELECT slug FROM molecules WHERE file_hash IS NULL").fetchall()
    if null_mols:
        mol_dir = brain_dir / "molecules"
        for row in null_mols:
            slug = row["slug"]
            md_path = mol_dir / f"{slug}.md"
            if md_path.exists():
                file_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
                conn.execute("UPDATE molecules SET file_hash = ? WHERE slug = ?", (file_hash, slug))
                count += 1

    if count:
        conn.commit()
        print(f"Backfilled {count} file hashes (first sync on imported brain).", file=sys.stderr, flush=True)
    return count


def run_sync(conn: sqlite3.Connection, brain_dir: Path,
             dry_run: bool = False) -> dict:
    """Full sync: scan files, scan DB, compute diff, apply."""
    # On first sync of an imported brain, backfill hashes so diff is accurate
    _backfill_hashes(conn, brain_dir)

    file_state = scan_files(brain_dir)
    db_state = scan_db(conn)
    plan = compute_diff(file_state, db_state)
    return apply_sync(conn, brain_dir, plan, dry_run=dry_run)
