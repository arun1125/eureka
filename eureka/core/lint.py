"""Lint — mechanical brain health checks. Pure computation, no LLM calls."""

import re
import sqlite3
from datetime import date
from pathlib import Path

from eureka.core.db import atom_table
from eureka.core.embeddings import cosine_sim, _unpack_vector
from eureka.core.parser import parse_note

# Files to skip when scanning brain_dir root for atoms
_SKIP_FILES = {"SCHEMA.md", "index.md", "log.md", "README.md", "map.md"}

# Required frontmatter fields for atoms
_REQUIRED_FIELDS = {"type", "tags", "date"}


def lint(conn: sqlite3.Connection, brain_dir: Path, embeddings: dict = None) -> dict:
    """Run all lint checks and return a results dict.

    Args:
        conn: open brain.db connection
        brain_dir: path to the brain/ directory
        embeddings: optional dict {slug: list[float]}. If None, attempts
                    to load from the DB embeddings table.

    Returns dict with keys: orphans, broken_links, duplicates,
    missing_frontmatter, summary.
    """
    brain_dir = Path(brain_dir)

    orphans = _orphaned_atoms(conn)
    broken_links = _broken_wikilinks(conn, brain_dir)
    duplicates = _duplicate_atoms(conn, embeddings)
    missing_fm = _missing_frontmatter(brain_dir)

    tbl = atom_table(conn)
    total_atoms = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]

    n_orphans = len(orphans)
    n_broken = len(broken_links)
    n_dupes = len(duplicates)
    n_missing = len(missing_fm)
    issues = n_orphans + n_broken + n_dupes + n_missing
    denom = total_atoms * 4
    health_score = round(100 * (1 - issues / denom), 1) if denom > 0 else 100.0
    health_score = max(0.0, min(100.0, health_score))

    return {
        "orphans": orphans,
        "broken_links": broken_links,
        "duplicates": duplicates,
        "missing_frontmatter": missing_fm,
        "summary": {
            "total_atoms": total_atoms,
            "orphans": n_orphans,
            "broken_links": n_broken,
            "duplicates": n_dupes,
            "missing_frontmatter": n_missing,
            "health_score": health_score,
        },
    }


def write_report(result: dict, brain_dir: Path) -> Path:
    """Write a markdown lint report to brain/_lint/YYYY-MM-DD.md.

    Returns the path to the written file.
    """
    brain_dir = Path(brain_dir)
    lint_dir = brain_dir / "_lint"
    lint_dir.mkdir(exist_ok=True)

    s = result["summary"]
    today = date.today().isoformat()
    out = lint_dir / f"{today}.md"

    lines = [
        f"# Brain Lint — {today}",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total atoms | {s['total_atoms']} |",
        f"| Orphans | {s['orphans']} |",
        f"| Broken links | {s['broken_links']} |",
        f"| Duplicates | {s['duplicates']} |",
        f"| Missing frontmatter | {s['missing_frontmatter']} |",
        f"| **Health score** | **{s['health_score']}** |",
        "",
    ]

    if result["orphans"]:
        lines += ["## Orphaned Atoms", ""]
        for slug in result["orphans"]:
            lines.append(f"- `{slug}`")
        lines.append("")

    if result["broken_links"]:
        lines += ["## Broken Wikilinks", ""]
        for bl in result["broken_links"]:
            lines.append(f"- `{bl['file']}` → `[[{bl['broken_link']}]]`")
        lines.append("")

    if result["duplicates"]:
        lines += ["## Potential Duplicates", ""]
        for d in result["duplicates"]:
            lines.append(f"- `{d['a']}` ↔ `{d['b']}` (sim: {d['similarity']:.3f})")
        lines.append("")

    if result["missing_frontmatter"]:
        lines += ["## Missing Frontmatter", ""]
        for mf in result["missing_frontmatter"]:
            lines.append(f"- `{mf['slug']}` — missing: {', '.join(mf['missing'])}")
        lines.append("")

    out.write_text("\n".join(lines))
    return out


# ---------------------------------------------------------------------------
# Internal checks
# ---------------------------------------------------------------------------

def _orphaned_atoms(conn: sqlite3.Connection) -> list[str]:
    """Atoms with zero inbound edges AND not in any molecule."""
    tbl = atom_table(conn)
    rows = conn.execute(f"""
        SELECT slug FROM {tbl}
        WHERE slug NOT IN (SELECT target FROM edges)
          AND slug NOT IN (SELECT atom_slug FROM molecule_atoms)
    """).fetchall()
    return [r["slug"] for r in rows]


def _broken_wikilinks(conn: sqlite3.Connection, brain_dir: Path) -> list[dict]:
    """Scan .md files for [[slug]] references to non-existent atoms."""
    tbl = atom_table(conn)
    existing = {
        r["slug"]
        for r in conn.execute(f"SELECT slug FROM {tbl}").fetchall()
    }

    wikilink_re = re.compile(r"\[\[([^\]]+)\]\]")
    broken = []

    # Collect files to scan: brain root atoms + molecules
    files: list[Path] = []
    for f in brain_dir.glob("*.md"):
        if f.name not in _SKIP_FILES:
            files.append(f)
    mol_dir = brain_dir / "molecules"
    if mol_dir.is_dir():
        files.extend(mol_dir.glob("*.md"))

    for f in files:
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        source_slug = f.stem
        for match in wikilink_re.findall(text):
            ref = match.strip()
            if ref and ref not in existing:
                broken.append({"file": source_slug, "broken_link": ref})

    return broken


def _duplicate_atoms(conn: sqlite3.Connection, embeddings: dict = None) -> list[dict]:
    """Find atom pairs with cosine similarity > 0.95.

    Uses provided embeddings dict or falls back to DB embeddings table.
    Returns up to 20 pairs sorted by similarity descending.
    """
    if embeddings is None:
        embeddings = _load_embeddings_from_db(conn)
    if not embeddings:
        return []

    slugs = sorted(embeddings.keys())
    pairs = []

    for i in range(len(slugs)):
        for j in range(i + 1, len(slugs)):
            sim = cosine_sim(embeddings[slugs[i]], embeddings[slugs[j]])
            if sim > 0.95:
                pairs.append({
                    "a": slugs[i],
                    "b": slugs[j],
                    "similarity": round(sim, 4),
                })

    pairs.sort(key=lambda p: p["similarity"], reverse=True)
    return pairs[:20]


def _load_embeddings_from_db(conn: sqlite3.Connection) -> dict:
    """Load all embeddings from the DB into {slug: vector} dict."""
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["slug"]] = _unpack_vector(r["vector"])
        except Exception:
            continue
    return out


def _missing_frontmatter(brain_dir: Path) -> list[dict]:
    """Check atom .md files for missing required frontmatter fields.

    Uses parse_note for files with the title/tags format, and also checks
    for YAML frontmatter (--- blocks) with type/date fields.
    """
    brain_dir = Path(brain_dir)
    results = []

    for f in brain_dir.glob("*.md"):
        if f.name in _SKIP_FILES:
            continue

        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        slug = f.stem
        found_fields: set[str] = set()

        # Check YAML frontmatter (--- delimited block at top)
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                fm_block = parts[1]
                for line in fm_block.splitlines():
                    line = line.strip()
                    if ":" in line:
                        key = line.split(":", 1)[0].strip().lower()
                        if key in _REQUIRED_FIELDS:
                            found_fields.add(key)

        # Also check parser output (tags: line at bottom)
        try:
            parsed = parse_note(f)
            if parsed.get("tags"):
                found_fields.add("tags")
        except Exception:
            pass

        # Check for inline type: and date: anywhere (some atoms use non-YAML format)
        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("type:"):
                found_fields.add("type")
            elif stripped.startswith("date:"):
                found_fields.add("date")
            elif stripped.startswith("tags:"):
                found_fields.add("tags")

        missing = sorted(_REQUIRED_FIELDS - found_fields)
        if missing:
            results.append({"slug": slug, "missing": missing})

    return results
