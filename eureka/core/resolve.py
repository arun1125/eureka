"""Resolve — close the decide loop by recording decision outcomes.

Tracks what actually happened after a decision was made, and over time
detects patterns in decision quality.
"""

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.activity import log_activity
from eureka.core.db import transaction


def resolve(
    conn: sqlite3.Connection,
    slug: str,
    outcome: str,
    brain_dir: Path | None = None,
) -> dict:
    """Record the outcome of a decision.

    Args:
        conn: open brain.db connection
        slug: decision molecule slug (e.g. "decision-should-i-move-to-bangkok")
        outcome: what actually happened
        brain_dir: path to brain directory (to update the molecule .md file)

    Returns dict with slug, outcome, resolved_at, and updated molecule info.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Find the decision row
    row = conn.execute(
        "SELECT id, question, result_json, molecule_slug FROM decisions WHERE molecule_slug = ?",
        (slug,),
    ).fetchone()

    if row is None:
        # Try matching by slug prefix (user might pass partial)
        rows = conn.execute(
            "SELECT id, question, result_json, molecule_slug FROM decisions "
            "WHERE molecule_slug LIKE ?",
            (f"%{slug}%",),
        ).fetchall()
        if len(rows) == 1:
            row = rows[0]
        elif len(rows) > 1:
            return {
                "error": "ambiguous_slug",
                "message": f"Multiple decisions match '{slug}'",
                "matches": [r["molecule_slug"] for r in rows],
            }
        else:
            return {
                "error": "not_found",
                "message": f"No decision found for slug '{slug}'",
            }

    decision_id = row["id"]
    molecule_slug = row["molecule_slug"]
    question = row["question"]

    # Update the decision row
    with transaction(conn):
        conn.execute(
            "UPDATE decisions SET outcome = ?, resolved_at = ? WHERE id = ?",
            (outcome, now, decision_id),
        )

    # Update the molecule .md file if brain_dir provided
    if brain_dir is not None:
        _update_molecule_file(brain_dir, molecule_slug, outcome, now)

    # Log activity
    log_activity(conn, "resolve", slug=molecule_slug, query=outcome)

    return {
        "slug": molecule_slug,
        "question": question,
        "outcome": outcome,
        "resolved_at": now,
    }


def patterns(conn: sqlite3.Connection) -> dict:
    """Analyze decision patterns from resolved decisions.

    Returns insights about decision-making quality and tendencies.
    """
    rows = conn.execute(
        "SELECT question, result_json, outcome, molecule_slug, created_at, resolved_at "
        "FROM decisions WHERE outcome IS NOT NULL"
    ).fetchall()

    if not rows:
        return {
            "total_resolved": 0,
            "message": "No resolved decisions yet. Use `eureka resolve` to record outcomes.",
        }

    total_resolved = len(rows)

    # Calculate average decision-to-resolution time
    resolution_times = []
    for row in rows:
        if row["created_at"] and row["resolved_at"]:
            try:
                created = datetime.fromisoformat(row["created_at"])
                resolved = datetime.fromisoformat(row["resolved_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if resolved.tzinfo is None:
                    resolved = resolved.replace(tzinfo=timezone.utc)
                days = (resolved - created).days
                resolution_times.append(days)
            except (ValueError, TypeError):
                continue

    avg_resolution_days = (
        round(sum(resolution_times) / len(resolution_times), 1)
        if resolution_times else None
    )

    # Analyze recommendation vs outcome alignment
    alignments = []
    for row in rows:
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
                recommendation = result.get("recommendation", "")
                alignments.append({
                    "question": row["question"],
                    "recommendation": recommendation[:200],
                    "outcome": row["outcome"],
                    "slug": row["molecule_slug"],
                })
            except (json.JSONDecodeError, TypeError):
                continue

    # Count unresolved decisions
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE outcome IS NULL"
    ).fetchone()[0]

    # Pending decisions (oldest first)
    pending = conn.execute(
        "SELECT question, molecule_slug, created_at FROM decisions "
        "WHERE outcome IS NULL ORDER BY created_at ASC LIMIT 5"
    ).fetchall()

    pending_list = [
        {
            "question": r["question"],
            "slug": r["molecule_slug"],
            "created_at": r["created_at"],
            "age_days": _days_ago(r["created_at"]),
        }
        for r in pending
    ]

    return {
        "total_resolved": total_resolved,
        "total_unresolved": unresolved,
        "avg_resolution_days": avg_resolution_days,
        "decisions": alignments,
        "pending_decisions": pending_list,
    }


def _days_ago(iso_str: str | None) -> int | None:
    """Calculate days since an ISO datetime string."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return None


def _update_molecule_file(
    brain_dir: Path,
    slug: str,
    outcome: str,
    resolved_at: str,
) -> None:
    """Append an Outcome section to the decision molecule markdown file."""
    mol_path = brain_dir / "molecules" / f"{slug}.md"
    if not mol_path.exists():
        return

    text = mol_path.read_text()

    # Don't append if outcome section already exists
    if "\n## Outcome" in text:
        return

    outcome_section = (
        f"\n## Outcome\n"
        f"*Resolved: {resolved_at[:10]}*\n\n"
        f"{outcome}\n"
    )

    mol_path.write_text(text.rstrip() + "\n" + outcome_section)
