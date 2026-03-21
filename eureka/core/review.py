"""Review logic — accept or reject molecules."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$')


class ReviewError(Exception):
    pass


def _validate_slug(slug: str):
    """Reject slugs that could cause path traversal."""
    if not slug or '..' in slug or '/' in slug or '\\' in slug:
        raise ReviewError(f"Invalid slug: {slug!r}")
    if not SLUG_RE.match(slug):
        raise ReviewError(f"Invalid slug format: {slug!r}")


def _get_molecule(conn: sqlite3.Connection, slug: str):
    row = conn.execute(
        "SELECT slug, review_status FROM molecules WHERE slug = ?", (slug,)
    ).fetchone()
    if row is None:
        raise ReviewError(f"Molecule not found: {slug}")
    if row["review_status"] != "pending":
        raise ReviewError(
            f"Molecule already reviewed ({row['review_status']}): {slug}"
        )
    return row


def accept_molecule(
    conn: sqlite3.Connection, slug: str, brain_dir: Path
) -> None:
    _validate_slug(slug)
    _get_molecule(conn, slug)
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE molecules SET review_status = 'accepted', reviewed_at = ? WHERE slug = ?",
        (now, slug),
    )
    conn.execute(
        "INSERT INTO reviews (slug, decision, reviewed_at) VALUES (?, 'accepted', ?)",
        (slug, now),
    )
    conn.commit()


def reject_molecule(
    conn: sqlite3.Connection, slug: str, brain_dir: Path
) -> None:
    _validate_slug(slug)
    _get_molecule(conn, slug)
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE molecules SET review_status = 'rejected', reviewed_at = ? WHERE slug = ?",
        (now, slug),
    )
    conn.execute(
        "INSERT INTO reviews (slug, decision, reviewed_at) VALUES (?, 'rejected', ?)",
        (slug, now),
    )
    conn.commit()

    # Delete the .md file (with path containment check)
    mol_dir = Path(brain_dir).resolve() / "molecules"
    md_path = (mol_dir / f"{slug}.md").resolve()
    if md_path.parent == mol_dir and md_path.exists():
        md_path.unlink()
