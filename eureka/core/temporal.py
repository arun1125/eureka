"""Temporal — reasoning over the brain's knowledge graph over time.

Pure computation, no LLM calls. Surfaces trends, revisit candidates, and stale atoms.
"""

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

from eureka.core.db import atom_table, atom_title_expr
from eureka.core.embeddings import _unpack_vector, cosine_sim


def trends(conn: sqlite3.Connection, brain_dir, window_days: int = 30,
           compare_days: int = 30) -> dict:
    """Compare tag frequency between two time windows to show focus shifts.

    Args:
        window_days: Recent window size in days.
        compare_days: Prior window size in days (immediately before recent).

    Returns dict with rising/falling/new/disappeared tags and activity shifts.
    """
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=window_days)
    prior_start = recent_start - timedelta(days=compare_days)

    _atbl = atom_table(conn)

    # Fetch atoms with creation dates
    rows = conn.execute(
        f"SELECT slug, created_at FROM {_atbl} WHERE created_at IS NOT NULL"
    ).fetchall()

    recent_slugs = []
    prior_slugs = []
    for r in rows:
        try:
            created = datetime.fromisoformat(r["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if created >= recent_start:
            recent_slugs.append(r["slug"])
        elif created >= prior_start:
            prior_slugs.append(r["slug"])

    # Count tags per window
    recent_tags = _count_tags(conn, recent_slugs)
    prior_tags = _count_tags(conn, prior_slugs)

    recent_total = sum(recent_tags.values()) or 1
    prior_total = sum(prior_tags.values()) or 1

    all_tags = set(recent_tags.keys()) | set(prior_tags.keys())

    rising = []
    falling = []
    new_tags = []
    disappeared = []

    for tag in all_tags:
        r_count = recent_tags.get(tag, 0)
        p_count = prior_tags.get(tag, 0)
        r_pct = round(r_count / recent_total * 100, 1)
        p_pct = round(p_count / prior_total * 100, 1)

        if p_count == 0 and r_count > 0:
            new_tags.append(tag)
        elif r_count == 0 and p_count > 0:
            disappeared.append(tag)
        elif r_pct > p_pct:
            rising.append({"tag": tag, "recent_pct": r_pct, "prior_pct": p_pct})
        elif r_pct < p_pct:
            falling.append({"tag": tag, "recent_pct": r_pct, "prior_pct": p_pct})

    rising.sort(key=lambda x: x["recent_pct"] - x["prior_pct"], reverse=True)
    falling.sort(key=lambda x: x["prior_pct"] - x["recent_pct"], reverse=True)

    # Activity shift between windows
    activity_shift = _activity_shift(conn, recent_start, prior_start, now)

    return {
        "window": {
            "start": recent_start.isoformat(),
            "end": now.isoformat(),
            "atom_count": len(recent_slugs),
        },
        "compare": {
            "start": prior_start.isoformat(),
            "end": recent_start.isoformat(),
            "atom_count": len(prior_slugs),
        },
        "rising_tags": rising,
        "falling_tags": falling,
        "new_tags": sorted(new_tags),
        "disappeared_tags": sorted(disappeared),
        "activity_shift": activity_shift,
    }


def revisit(conn: sqlite3.Connection, embeddings, brain_dir,
            max_results: int = 10) -> list[dict]:
    """Surface old atoms newly relevant based on recent activity.

    Args:
        embeddings: unused (kept for API compat); vectors come from DB.
        max_results: Max atoms to return.

    Returns list of dicts with slug, title, age_days, relevance, reason.
    """
    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(days=14)
    cutoff_old = now - timedelta(days=30)

    _atbl = atom_table(conn)
    _title_expr = atom_title_expr(conn)

    # Get recent activity slugs (last 14 days)
    recent_rows = conn.execute(
        "SELECT DISTINCT slug FROM activity "
        "WHERE slug IS NOT NULL AND timestamp >= ?",
        (cutoff_recent.isoformat(),),
    ).fetchall()
    recent_slugs = {r["slug"] for r in recent_rows}

    if not recent_slugs:
        return []

    # Compute centroid of recent activity embeddings
    recent_vectors = []
    for slug in recent_slugs:
        row = conn.execute(
            "SELECT vector FROM embeddings WHERE slug = ?", (slug,)
        ).fetchone()
        if row:
            recent_vectors.append(_unpack_vector(row["vector"]))

    if not recent_vectors:
        return []

    dim = len(recent_vectors[0])
    centroid = [0.0] * dim
    for vec in recent_vectors:
        for i in range(dim):
            centroid[i] += vec[i]
    centroid = [v / len(recent_vectors) for v in centroid]

    # Find top recent tag for reason strings
    recent_tags = _count_tags(conn, list(recent_slugs))
    top_tag = max(recent_tags, key=recent_tags.get) if recent_tags else "recent topics"

    # Get old atoms not in recent activity
    old_atoms = conn.execute(
        f"SELECT slug, {_title_expr} AS title, created_at FROM {_atbl} "
        "WHERE created_at IS NOT NULL"
    ).fetchall()

    candidates = []
    for atom in old_atoms:
        if atom["slug"] in recent_slugs:
            continue
        try:
            created = datetime.fromisoformat(atom["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if created > cutoff_old:
            continue  # Not old enough

        emb_row = conn.execute(
            "SELECT vector FROM embeddings WHERE slug = ?", (atom["slug"],)
        ).fetchone()
        if not emb_row:
            continue

        vec = _unpack_vector(emb_row["vector"])
        sim = cosine_sim(centroid, vec)
        age_days = (now - created).days

        candidates.append({
            "slug": atom["slug"],
            "title": atom["title"],
            "age_days": age_days,
            "relevance": round(sim, 4),
            "reason": f"Created {age_days} days ago, relevant to your recent focus on {top_tag}",
        })

    candidates.sort(key=lambda c: c["relevance"], reverse=True)
    return candidates[:max_results]


def staleness(conn: sqlite3.Connection, brain_dir,
              threshold_days: int = 90) -> list[dict]:
    """Find atoms not referenced in activity for a long time.

    Args:
        threshold_days: Minimum days since last activity to be considered stale.

    Returns list of dicts with slug, created_days_ago, last_active_days_ago,
    in_molecules.
    """
    now = datetime.now(timezone.utc)
    _atbl = atom_table(conn)

    # All atoms with creation dates
    atoms = conn.execute(
        f"SELECT slug, created_at FROM {_atbl} WHERE created_at IS NOT NULL"
    ).fetchall()

    # Last activity per slug
    activity_rows = conn.execute(
        "SELECT slug, MAX(timestamp) AS last_ts FROM activity "
        "WHERE slug IS NOT NULL GROUP BY slug"
    ).fetchall()
    last_active: dict[str, str] = {r["slug"]: r["last_ts"] for r in activity_rows}

    # Molecule membership counts
    mol_rows = conn.execute(
        "SELECT atom_slug, COUNT(*) AS cnt FROM molecule_atoms GROUP BY atom_slug"
    ).fetchall()
    mol_counts: dict[str, int] = {r["atom_slug"]: r["cnt"] for r in mol_rows}

    results = []
    for atom in atoms:
        try:
            created = datetime.fromisoformat(atom["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        created_days_ago = (now - created).days
        slug = atom["slug"]

        last_ts = last_active.get(slug)
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                last_active_days_ago = (now - last_dt).days
            except (ValueError, TypeError):
                last_active_days_ago = None
        else:
            last_active_days_ago = None

        # Stale if: never referenced AND old enough, OR last referenced long ago
        is_stale = False
        if last_active_days_ago is None and created_days_ago >= threshold_days:
            is_stale = True
        elif last_active_days_ago is not None and last_active_days_ago >= threshold_days:
            is_stale = True

        if is_stale:
            results.append({
                "slug": slug,
                "created_days_ago": created_days_ago,
                "last_active_days_ago": last_active_days_ago,
                "in_molecules": mol_counts.get(slug, 0),
            })

    # Sort: most stale first (longest since any activity)
    results.sort(
        key=lambda r: r["last_active_days_ago"] if r["last_active_days_ago"] is not None
        else r["created_days_ago"],
        reverse=True,
    )
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _count_tags(conn: sqlite3.Connection, slugs: list[str]) -> Counter:
    """Count tag frequency across a list of atom slugs."""
    counts: Counter = Counter()
    for slug in slugs:
        rows = conn.execute(
            "SELECT t.name FROM tags t JOIN note_tags nt ON t.id = nt.tag_id "
            "WHERE nt.slug = ?",
            (slug,),
        ).fetchall()
        for r in rows:
            counts[r["name"]] += 1
    return counts


def _activity_shift(conn: sqlite3.Connection, recent_start: datetime,
                    prior_start: datetime, now: datetime) -> list[dict]:
    """Compare activity type counts between recent and prior windows."""
    recent_rows = conn.execute(
        "SELECT type, COUNT(*) AS cnt FROM activity "
        "WHERE timestamp >= ? GROUP BY type",
        (recent_start.isoformat(),),
    ).fetchall()
    prior_rows = conn.execute(
        "SELECT type, COUNT(*) AS cnt FROM activity "
        "WHERE timestamp >= ? AND timestamp < ? GROUP BY type",
        (prior_start.isoformat(), recent_start.isoformat()),
    ).fetchall()

    recent_counts = {r["type"]: r["cnt"] for r in recent_rows}
    prior_counts = {r["type"]: r["cnt"] for r in prior_rows}

    all_types = set(recent_counts.keys()) | set(prior_counts.keys())
    results = []
    for t in sorted(all_types):
        results.append({
            "type": t,
            "recent_count": recent_counts.get(t, 0),
            "prior_count": prior_counts.get(t, 0),
        })

    return results
