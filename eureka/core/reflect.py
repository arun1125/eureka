"""Reflect — brain-wide self-assessment. Pure computation, no LLM calls."""

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from eureka.core.pushback import detect_patterns, detect_goal_gaps
from eureka.core.profile import get_profile


def reflect(conn: sqlite3.Connection, brain_dir) -> dict:
    """Return a 6-key self-assessment dict.

    Keys: active_topics, recurring_patterns, blind_spots,
          goal_alignment, pending_review, molecules_to_revisit.
    """
    return {
        "active_topics": _active_topics(conn),
        "recurring_patterns": _recurring_patterns(conn),
        "blind_spots": _blind_spots(conn),
        "goal_alignment": _goal_alignment(conn),
        "pending_review": _pending_review(conn),
        "molecules_to_revisit": _molecules_to_revisit(conn),
    }


def _active_topics(conn: sqlite3.Connection) -> list[str]:
    """Most frequent tags from recent activity slugs."""
    rows = conn.execute(
        "SELECT slug FROM activity WHERE slug IS NOT NULL "
        "ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    slugs = [r["slug"] for r in rows]
    if not slugs:
        return []

    tag_counts: Counter = Counter()
    for slug in slugs:
        tag_rows = conn.execute(
            "SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id "
            "WHERE nt.slug = ?",
            (slug,),
        ).fetchall()
        for tr in tag_rows:
            tag_counts[tr["name"]] += 1

    # Return unique tags sorted by frequency (descending)
    return [tag for tag, _ in tag_counts.most_common()]


def _recurring_patterns(conn: sqlite3.Connection) -> list[dict]:
    """Detect recurring themes from all recent activity slugs."""
    rows = conn.execute(
        "SELECT DISTINCT slug FROM activity WHERE slug IS NOT NULL"
    ).fetchall()
    slugs = [r["slug"] for r in rows]
    return detect_patterns(conn, slugs)


def _blind_spots(conn: sqlite3.Connection) -> list[dict]:
    """Find tag pairs that both have 2+ atoms but share few cross-tag edges."""
    # Get all tags with their atom slugs
    tag_atoms: dict[str, set[str]] = {}
    rows = conn.execute(
        "SELECT t.name, nt.slug FROM tags t JOIN note_tags nt ON t.id = nt.tag_id"
    ).fetchall()
    for r in rows:
        tag_atoms.setdefault(r["name"], set()).add(r["slug"])

    # Get all edges as a set for fast lookup
    edge_rows = conn.execute("SELECT source, target FROM edges").fetchall()
    edges_set: set[tuple[str, str]] = set()
    for e in edge_rows:
        edges_set.add((e["source"], e["target"]))
        edges_set.add((e["target"], e["source"]))

    # Check all tag pairs where both have >= 2 atoms
    tag_names = [t for t, atoms in tag_atoms.items() if len(atoms) >= 2]
    blind_spots = []
    seen: set[tuple[str, str]] = set()

    for i, t1 in enumerate(tag_names):
        for t2 in tag_names[i + 1:]:
            key = (min(t1, t2), max(t1, t2))
            if key in seen:
                continue
            seen.add(key)

            # Count cross-tag edges
            cross_edges = 0
            for a1 in tag_atoms[t1]:
                for a2 in tag_atoms[t2]:
                    if a1 == a2:
                        continue
                    if (a1, a2) in edges_set:
                        cross_edges += 1

            if cross_edges <= 1:
                blind_spots.append({
                    "topic_a": t1,
                    "topic_b": t2,
                    "note": f"'{t1}' and '{t2}' each have atoms but few connections between them.",
                })

    return blind_spots


def _goal_alignment(conn: sqlite3.Connection) -> list[dict]:
    """Assess brain coverage for each profile goal."""
    profile = get_profile(conn)
    if not profile:
        return []

    # Get all atom titles and tags for coverage check
    from eureka.core.db import atom_table, atom_title_expr
    _atbl = atom_table(conn)
    _title_expr = atom_title_expr(conn)
    atoms = conn.execute(f"SELECT slug, {_title_expr} AS title FROM {_atbl}").fetchall()
    atom_words: set[str] = set()
    for a in atoms:
        for w in a["title"].lower().split():
            if len(w) > 2:
                atom_words.add(w)
        for w in a["slug"].split("-"):
            if len(w) > 2:
                atom_words.add(w)

    # Also gather all tag names
    tag_rows = conn.execute("SELECT name FROM tags").fetchall()
    tag_words = {r["name"].lower() for r in tag_rows}
    all_words = atom_words | tag_words

    # Also use detect_goal_gaps for gap detection
    gaps = detect_goal_gaps(conn)
    gap_keys = {g["goal_key"] for g in gaps}

    results = []
    for entry in profile:
        goal_value = entry["value"]
        goal_key = entry["key"]
        goal_words = {w.lower() for w in goal_value.split() if len(w) > 2}

        overlap = goal_words & all_words
        ratio = len(overlap) / len(goal_words) if goal_words else 0

        if ratio >= 0.4:
            coverage = "strong"
            note = f"Good coverage — atoms touch: {', '.join(sorted(overlap)[:5])}"
        elif ratio > 0 or goal_key not in gap_keys:
            coverage = "weak"
            note = f"Partial coverage — overlapping words: {', '.join(sorted(overlap)[:5]) if overlap else 'few'}"
        else:
            coverage = "none"
            note = f"No atoms or activity related to this goal."

        results.append({
            "goal": goal_value,
            "brain_coverage": coverage,
            "note": note,
        })

    return results


def _pending_review(conn: sqlite3.Connection) -> int:
    """Count molecules with review_status = 'pending'."""
    row = conn.execute(
        "SELECT COUNT(*) FROM molecules WHERE review_status = 'pending'"
    ).fetchone()
    return row[0]


def _molecules_to_revisit(conn: sqlite3.Connection) -> list[dict]:
    """Accepted molecules with reviewed_at older than 14 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows = conn.execute(
        "SELECT slug, eli5, reviewed_at FROM molecules "
        "WHERE review_status = 'accepted' AND reviewed_at IS NOT NULL AND reviewed_at < ?",
        (cutoff,),
    ).fetchall()

    results = []
    for r in rows:
        try:
            reviewed = datetime.fromisoformat(r["reviewed_at"])
            if reviewed.tzinfo is None:
                reviewed = reviewed.replace(tzinfo=timezone.utc)
            days_ago = (datetime.now(timezone.utc) - reviewed).days
        except (ValueError, TypeError):
            days_ago = 14

        results.append({
            "slug": r["slug"],
            "eli5": r["eli5"],
            "reason": f"Accepted {days_ago} days ago. Does it still hold?",
        })

    return results
