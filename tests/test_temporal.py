"""Tests for eureka temporal — trends, revisit, staleness."""

import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eureka.core.db import open_db, ensure_tag, tag_note
from eureka.core.embeddings import _deterministic_embed


def _seed_brain(tmp_path, atoms=None):
    """Create a brain with atoms. Returns (brain_dir, conn)."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()
    (brain_dir / "molecules").mkdir()

    if atoms is None:
        atoms = {
            "remote-work-unlocks-geographic-arbitrage": {
                "title": "Remote work unlocks geographic arbitrage",
                "body": "If your income is location-independent, moving to a cheaper city is a free raise.",
                "tags": ["lifestyle", "money"],
            },
            "barbell-strategy": {
                "title": "Barbell strategy",
                "body": "Put 90% in safe assets and 10% in high-risk bets. Avoid the middle.",
                "tags": ["risk", "strategy"],
            },
            "skin-in-the-game": {
                "title": "Skin in the game",
                "body": "Never trust advice from someone who doesn't bear the downside of being wrong.",
                "tags": ["risk", "decision-making"],
            },
        }

    for slug, data in atoms.items():
        tags_str = ", ".join(data["tags"])
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {tags_str}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    from eureka.core.linker import link_all
    link_all(conn)

    return brain_dir, conn


def _load_embeddings(conn):
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    emb = {}
    for r in rows:
        dim = len(r["vector"]) // 4
        emb[r["slug"]] = list(struct.unpack(f"{dim}f", r["vector"]))
    return emb


# ---------------------------------------------------------------------------
# trends
# ---------------------------------------------------------------------------

def test_trends_basic(tmp_path):
    """Atoms with dates in two windows produce rising/falling tags."""
    now = datetime.now(timezone.utc)
    atoms = {
        "recent-alpha": {
            "title": "Recent alpha topic",
            "body": "This is about alpha and innovation.",
            "tags": ["alpha"],
        },
        "recent-alpha-2": {
            "title": "Another alpha topic",
            "body": "More alpha content here.",
            "tags": ["alpha"],
        },
        "old-beta": {
            "title": "Old beta topic",
            "body": "This was about beta and legacy.",
            "tags": ["beta"],
        },
        "old-beta-2": {
            "title": "Another beta topic",
            "body": "More beta content here.",
            "tags": ["beta"],
        },
    }
    brain_dir, conn = _seed_brain(tmp_path, atoms)

    # Move recent atoms to 10 days ago (within default 30-day window)
    recent_date = (now - timedelta(days=10)).isoformat()
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (recent_date, "recent-alpha"))
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (recent_date, "recent-alpha-2"))

    # Move old atoms to 45 days ago (within 30-60 day compare window)
    old_date = (now - timedelta(days=45)).isoformat()
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (old_date, "old-beta"))
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (old_date, "old-beta-2"))
    conn.commit()

    from eureka.core.temporal import trends
    result = trends(conn, brain_dir, window_days=30, compare_days=30)

    assert "new_tags" in result or "rising_tags" in result
    assert "disappeared_tags" in result or "falling_tags" in result

    # Alpha should be new/rising (only in recent window)
    new_or_rising = result.get("new_tags", [])
    rising_tag_names = [r["tag"] for r in result.get("rising_tags", [])]
    assert "alpha" in new_or_rising or "alpha" in rising_tag_names

    # Beta should be disappeared/falling (only in prior window)
    gone_or_falling = result.get("disappeared_tags", [])
    falling_tag_names = [r["tag"] for r in result.get("falling_tags", [])]
    assert "beta" in gone_or_falling or "beta" in falling_tag_names

    conn.close()


def test_trends_empty_brain(tmp_path):
    """Empty brain returns structure without crashing."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    (brain_dir / "molecules").mkdir()
    conn = open_db(brain_dir / "brain.db")

    from eureka.core.temporal import trends
    result = trends(conn, brain_dir)

    # Should return dict with expected keys, all empty
    assert isinstance(result, dict)
    assert result.get("rising_tags", []) == []
    assert result.get("falling_tags", []) == []
    assert result.get("new_tags", []) == []
    assert result.get("disappeared_tags", []) == []

    conn.close()


# ---------------------------------------------------------------------------
# revisit
# ---------------------------------------------------------------------------

def test_revisit_surfaces_old_relevant(tmp_path):
    """Old atoms similar to recent activity appear in revisit results."""
    now = datetime.now(timezone.utc)
    atoms = {
        "old-risk-management": {
            "title": "Risk management fundamentals",
            "body": "Risk management is about identifying and mitigating downside risk.",
            "tags": ["risk", "strategy"],
        },
        "old-portfolio-theory": {
            "title": "Portfolio theory basics",
            "body": "Diversification reduces risk across a portfolio of assets.",
            "tags": ["risk", "investing"],
        },
        "recent-decision-risk": {
            "title": "Decision making under risk",
            "body": "Making decisions under uncertainty requires understanding risk.",
            "tags": ["risk", "decision-making"],
        },
    }
    brain_dir, conn = _seed_brain(tmp_path, atoms)

    # Make first two atoms old (60+ days)
    old_date = (now - timedelta(days=90)).isoformat()
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (old_date, "old-risk-management"))
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (old_date, "old-portfolio-theory"))

    # Keep recent atom recent
    recent_date = (now - timedelta(days=5)).isoformat()
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (recent_date, "recent-decision-risk"))

    # Add recent activity for the recent atom
    conn.execute(
        "INSERT INTO activity (type, slug, timestamp) VALUES ('ask', ?, ?)",
        ("recent-decision-risk", (now - timedelta(days=2)).isoformat()),
    )
    conn.commit()

    embeddings = _load_embeddings(conn)

    from eureka.core.temporal import revisit
    result = revisit(conn, embeddings, brain_dir, max_results=10)

    assert isinstance(result, list)
    assert len(result) > 0
    slugs = [r["slug"] for r in result]
    # At least one old atom should surface (they share "risk" topic)
    assert any(s in slugs for s in ["old-risk-management", "old-portfolio-theory"])

    conn.close()


def test_revisit_empty(tmp_path):
    """No recent activity returns empty list."""
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)

    from eureka.core.temporal import revisit
    result = revisit(conn, embeddings, brain_dir)

    assert result == []
    conn.close()


# ---------------------------------------------------------------------------
# staleness
# ---------------------------------------------------------------------------

def test_staleness_finds_stale(tmp_path):
    """Atoms with old created_at and no activity are flagged as stale."""
    now = datetime.now(timezone.utc)
    atoms = {
        "ancient-atom": {
            "title": "Ancient forgotten atom",
            "body": "This atom has not been touched in a very long time.",
            "tags": ["forgotten"],
        },
        "fresh-atom": {
            "title": "Fresh recent atom",
            "body": "This atom was just created recently.",
            "tags": ["active"],
        },
    }
    brain_dir, conn = _seed_brain(tmp_path, atoms)

    # Make ancient-atom 120 days old, no activity
    old_date = (now - timedelta(days=120)).isoformat()
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (old_date, "ancient-atom"))

    # Keep fresh-atom recent
    recent_date = (now - timedelta(days=5)).isoformat()
    conn.execute("UPDATE atoms SET created_at = ? WHERE slug = ?", (recent_date, "fresh-atom"))
    conn.commit()

    from eureka.core.temporal import staleness
    result = staleness(conn, brain_dir, threshold_days=90)

    assert isinstance(result, list)
    stale_slugs = [r["slug"] for r in result]
    assert "ancient-atom" in stale_slugs
    assert "fresh-atom" not in stale_slugs

    # Check structure of result entries
    ancient = [r for r in result if r["slug"] == "ancient-atom"][0]
    assert ancient["created_days_ago"] >= 119  # allow 1 day variance
    assert ancient["last_active_days_ago"] is None  # no activity recorded

    conn.close()
