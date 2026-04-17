"""Tests for eureka resolve — decision outcome tracking and pattern analysis."""

import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.db import open_db, transaction
from eureka.core.embeddings import _deterministic_embed


def _seed_brain_with_decision(tmp_path, question="Should I move to Bangkok?"):
    """Create a brain with a filed decision ready for resolution."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    mol_dir = brain_dir / "molecules"
    mol_dir.mkdir()

    conn = open_db(brain_dir / "brain.db")

    # Create a decision molecule
    slug = "decision-should-i-move-to-bangkok"
    result_json = json.dumps({
        "for_arguments": ["Lower cost of living"],
        "against_arguments": ["Far from family"],
        "tensions": ["Cost vs proximity"],
        "unknowns": ["Internet quality"],
        "recommendation": "Move, keep a 3-month buffer.",
    })

    with transaction(conn):
        conn.execute(
            "INSERT INTO molecules (slug, title, method, score, status, eli5, body) "
            "VALUES (?, ?, 'decision', 0, 'accepted', ?, ?)",
            (slug, f"Decision: {question}", "Move, keep a buffer.", "# Decision"),
        )
        conn.execute(
            "INSERT INTO decisions (question, result_json, molecule_slug) VALUES (?, ?, ?)",
            (question, result_json, slug),
        )

    # Write molecule file
    (mol_dir / f"{slug}.md").write_text(
        f"---\ntype: molecule\ntags: [decision]\n---\n\n# Decision: {question}\n\n## Recommendation\nMove.\n"
    )

    return brain_dir, conn, slug


def test_resolve_basic(tmp_path):
    """resolve records the outcome and returns expected fields."""
    brain_dir, conn, slug = _seed_brain_with_decision(tmp_path)

    from eureka.core.resolve import resolve
    result = resolve(conn, slug, "Moved to Bangkok, productivity doubled.", brain_dir=brain_dir)

    assert result["slug"] == slug
    assert result["outcome"] == "Moved to Bangkok, productivity doubled."
    assert "resolved_at" in result
    assert "error" not in result

    # Check DB was updated
    row = conn.execute("SELECT outcome, resolved_at FROM decisions WHERE molecule_slug = ?", (slug,)).fetchone()
    assert row["outcome"] == "Moved to Bangkok, productivity doubled."
    assert row["resolved_at"] is not None
    conn.close()


def test_resolve_updates_molecule_file(tmp_path):
    """resolve appends an Outcome section to the molecule markdown."""
    brain_dir, conn, slug = _seed_brain_with_decision(tmp_path)

    from eureka.core.resolve import resolve
    resolve(conn, slug, "It worked out great.", brain_dir=brain_dir)

    mol_path = brain_dir / "molecules" / f"{slug}.md"
    text = mol_path.read_text()
    assert "## Outcome" in text
    assert "It worked out great." in text
    conn.close()


def test_resolve_not_found(tmp_path):
    """resolve returns error for non-existent slug."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    (brain_dir / "molecules").mkdir()
    conn = open_db(brain_dir / "brain.db")

    from eureka.core.resolve import resolve
    result = resolve(conn, "decision-nonexistent", "some outcome")

    assert result["error"] == "not_found"
    conn.close()


def test_resolve_partial_slug_match(tmp_path):
    """resolve matches by partial slug when unambiguous."""
    brain_dir, conn, slug = _seed_brain_with_decision(tmp_path)

    from eureka.core.resolve import resolve
    result = resolve(conn, "move-to-bangkok", "Moved successfully.", brain_dir=brain_dir)

    assert result["slug"] == slug
    assert "error" not in result
    conn.close()


def test_resolve_no_duplicate_outcome_section(tmp_path):
    """resolve doesn't append a second Outcome section if one exists."""
    brain_dir, conn, slug = _seed_brain_with_decision(tmp_path)

    from eureka.core.resolve import resolve
    resolve(conn, slug, "First outcome.", brain_dir=brain_dir)
    # Resolve again — should not duplicate
    resolve(conn, slug, "Second outcome.", brain_dir=brain_dir)

    mol_path = brain_dir / "molecules" / f"{slug}.md"
    text = mol_path.read_text()
    assert text.count("## Outcome") == 1
    conn.close()


def test_patterns_no_decisions(tmp_path):
    """patterns returns a message when no decisions have been resolved."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    (brain_dir / "molecules").mkdir()
    conn = open_db(brain_dir / "brain.db")

    from eureka.core.resolve import patterns
    result = patterns(conn)

    assert result["total_resolved"] == 0
    assert "message" in result
    conn.close()


def test_patterns_with_resolved_decisions(tmp_path):
    """patterns returns analysis when resolved decisions exist."""
    brain_dir, conn, slug = _seed_brain_with_decision(tmp_path)

    # Resolve the decision
    from eureka.core.resolve import resolve
    resolve(conn, slug, "Moved to Bangkok, best decision ever.", brain_dir=brain_dir)

    from eureka.core.resolve import patterns
    result = patterns(conn)

    assert result["total_resolved"] == 1
    assert result["total_unresolved"] == 0
    assert len(result["decisions"]) == 1
    assert result["decisions"][0]["outcome"] == "Moved to Bangkok, best decision ever."
    conn.close()


def test_patterns_shows_pending(tmp_path):
    """patterns lists unresolved decisions with age after at least one resolved."""
    brain_dir, conn, slug = _seed_brain_with_decision(tmp_path)

    # Add a second decision and resolve it, leaving the first unresolved
    with transaction(conn):
        conn.execute(
            "INSERT INTO decisions (question, result_json, molecule_slug, outcome, resolved_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Should I learn Rust?", "{}", "decision-learn-rust", "Yes, learned it.", datetime.now(timezone.utc).isoformat()),
        )

    from eureka.core.resolve import patterns
    result = patterns(conn)

    assert result["total_resolved"] == 1
    assert result["total_unresolved"] == 1
    assert len(result["pending_decisions"]) == 1
    assert result["pending_decisions"][0]["slug"] == slug
    conn.close()
