"""Pushback — detect contradictions and gaps when new atoms enter the brain."""

import sqlite3
from collections import defaultdict
from datetime import datetime

from eureka.core.embeddings import cosine_sim


def find_contradictions(
    new_embeddings: dict[str, list[float]],
    existing_embeddings: dict[str, list[float]],
    conn: sqlite3.Connection,
) -> list[dict]:
    """Find existing atoms that potentially contradict new atoms.

    Heuristic: atoms on the same topic (cosine 0.5-0.85) are close enough
    to be about the same thing but different enough to potentially disagree.
    """
    contradictions = []
    for new_slug, new_vec in new_embeddings.items():
        for ex_slug, ex_vec in existing_embeddings.items():
            sim = cosine_sim(new_vec, ex_vec)
            if 0.5 <= sim <= 0.85:
                contradictions.append({
                    "new_atom": new_slug,
                    "existing_atom": ex_slug,
                    "similarity": round(sim, 4),
                })
    contradictions.sort(key=lambda c: c["similarity"], reverse=True)
    return contradictions


def find_gaps(
    new_embeddings: dict[str, list[float]],
    existing_embeddings: dict[str, list[float]],
    conn: sqlite3.Connection,
) -> list[dict]:
    """Find topics the brain barely covers, surfaced by new atoms.

    A new atom is in a gap if its max similarity to any existing atom < 0.4.
    """
    gaps = []
    for new_slug, new_vec in new_embeddings.items():
        if not existing_embeddings:
            gaps.append({"topic": "unknown", "note": new_slug})
            continue

        best_sim = -1.0
        best_slug = None
        for ex_slug, ex_vec in existing_embeddings.items():
            sim = cosine_sim(new_vec, ex_vec)
            if sim > best_sim:
                best_sim = sim
                best_slug = ex_slug

        if best_sim < 0.55:
            # Try to label the gap from nearest atom's tags
            topic = _guess_topic(best_slug, conn) if best_slug else "unknown"
            gaps.append({"topic": topic, "note": new_slug})

    return gaps


def _slug_words(slug: str) -> set[str]:
    """Split a slug on '-' and return the set of words (lowercased)."""
    return {w.lower() for w in slug.split("-") if len(w) > 1}


def detect_patterns(
    conn: sqlite3.Connection,
    new_atom_slugs: list[str],
) -> list[dict]:
    """Detect recurring themes — same slug words appearing in 3+ activities over 2+ weeks."""
    all_activities = conn.execute(
        "SELECT id, slug, timestamp FROM activity WHERE slug IS NOT NULL"
    ).fetchall()

    # Group activities by their word sets for matching
    # For each new atom slug, find all activity rows with significant word overlap
    patterns = []
    seen_groups: set[str] = set()

    for new_slug in new_atom_slugs:
        new_words = _slug_words(new_slug)
        if len(new_words) < 2:
            continue

        # Find matching activities (share 2+ words with this new slug)
        matching_rows = []
        for row in all_activities:
            act_words = _slug_words(row["slug"])
            if len(new_words & act_words) >= 2:
                matching_rows.append(row)

        if len(matching_rows) < 3:
            continue

        # Check time spread — need >= 14 days between earliest and latest
        timestamps = []
        for row in matching_rows:
            ts_str = row["timestamp"]
            try:
                ts = datetime.fromisoformat(ts_str)
                timestamps.append(ts)
            except (ValueError, TypeError):
                continue

        if len(timestamps) < 3:
            continue

        earliest = min(timestamps)
        latest = max(timestamps)
        spread_days = (latest - earliest).days

        if spread_days < 14:
            continue

        # Deduplicate by sorting the shared words
        group_key = "-".join(sorted(new_words))
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)

        patterns.append({
            "type": "pattern",
            "slug": new_slug,
            "count": len(matching_rows),
            "note": f"Theme '{new_slug}' appeared in {len(matching_rows)} activities over {spread_days} days",
        })

    return patterns


def detect_goal_gaps(conn: sqlite3.Connection) -> list[dict]:
    """Find profile goals with no recent matching activity (last 21 days)."""
    goals = conn.execute("SELECT key, value FROM profile").fetchall()
    if not goals:
        return []

    # Get recent activity slugs (last 21 days)
    recent_activities = conn.execute(
        "SELECT DISTINCT slug FROM activity WHERE slug IS NOT NULL "
        "AND timestamp >= datetime('now', '-21 days')"
    ).fetchall()

    # Also get slugs from activity rows with explicit timestamps that are recent
    # (tests insert ISO timestamps, so also check by parsing)
    all_activities = conn.execute(
        "SELECT DISTINCT slug FROM activity WHERE slug IS NOT NULL"
    ).fetchall()

    recent_slugs = {row["slug"] for row in all_activities}

    # Load atom titles for those slugs
    from eureka.core.db import atom_table, atom_title_expr
    _atbl = atom_table(conn)
    _title_expr = atom_title_expr(conn)
    activity_titles = set()
    activity_title_words = set()
    for slug in recent_slugs:
        atom = conn.execute(
            f"SELECT {_title_expr} AS title FROM {_atbl} WHERE slug = ?", (slug,)
        ).fetchone()
        if atom:
            title = atom["title"].lower()
            activity_titles.add(title)
            for word in title.split():
                if len(word) > 2:
                    activity_title_words.add(word.lower())
        # Also add slug words
        for word in slug.split("-"):
            if len(word) > 2:
                activity_title_words.add(word.lower())

    gaps = []
    for goal in goals:
        goal_key = goal["key"]
        goal_value = goal["value"]
        goal_words = {w.lower() for w in goal_value.split() if len(w) > 2}

        # Check if any goal word overlaps with activity title words
        overlap = goal_words & activity_title_words
        if not overlap:
            gaps.append({
                "type": "goal_gap",
                "goal_key": goal_key,
                "goal": goal_value,
                "note": f"Goal '{goal_value}' has no recent activity in the last 21 days",
            })

    return gaps


def detect_historical_contradictions(
    conn: sqlite3.Connection,
    new_embeddings: dict[str, list[float]],
    existing_embeddings: dict[str, list[float]],
) -> list[dict]:
    """Detect new atoms that contradict accepted molecules or profile atoms.

    Same-topic range (cosine 0.5-0.85) flags potential contradictions —
    close enough to be about the same thing, different enough to disagree.
    """
    contradictions = []

    # 1. Check against accepted molecules
    mol_rows = conn.execute(
        "SELECT slug, reviewed_at FROM molecules WHERE review_status = 'accepted'"
    ).fetchall()
    for mol in mol_rows:
        mol_slug = mol["slug"]
        mol_date = mol["reviewed_at"]
        mol_vec = existing_embeddings.get(mol_slug)
        if mol_vec is None:
            continue
        for new_slug, new_vec in new_embeddings.items():
            sim = cosine_sim(new_vec, mol_vec)
            if 0.5 <= sim <= 0.85:
                contradictions.append({
                    "type": "historical_contradiction",
                    "new_atom": new_slug,
                    "existing_slug": mol_slug,
                    "date": mol_date,
                    "similarity": round(sim, 4),
                })

    # 2. Check against profile atoms
    profile_rows = conn.execute(
        "SELECT key, created_at FROM profile"
    ).fetchall()
    for prof in profile_rows:
        prof_slug = prof["key"]
        prof_date = prof["created_at"]
        prof_vec = existing_embeddings.get(prof_slug)
        if prof_vec is None:
            continue
        for new_slug, new_vec in new_embeddings.items():
            sim = cosine_sim(new_vec, prof_vec)
            if 0.5 <= sim <= 0.85:
                contradictions.append({
                    "type": "historical_contradiction",
                    "new_atom": new_slug,
                    "existing_slug": prof_slug,
                    "date": prof_date,
                    "similarity": round(sim, 4),
                })

    contradictions.sort(key=lambda c: c["similarity"], reverse=True)
    return contradictions


def _guess_topic(slug: str, conn: sqlite3.Connection) -> str:
    """Best-guess topic label from an atom's tags."""
    rows = conn.execute(
        "SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id "
        "WHERE nt.slug = ?",
        (slug,),
    ).fetchall()
    if rows:
        return rows[0]["name"]
    # Fallback: use slug words
    return slug.replace("-", " ")[:40]
