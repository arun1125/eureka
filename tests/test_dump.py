"""Tests for eureka dump — extract atoms from raw text, connect to brain."""

import json
import struct
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.embeddings import embed_text


def _seed_brain(tmp_path):
    """Create a brain with a few atoms so dump has something to connect to."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    # Write some existing atoms
    atoms = {
        "niching-down-lets-you-charge-100x": {
            "title": "Niching down lets you charge 100x for the same product",
            "body": "When you specialize, competition drops and perceived value rises.",
            "tags": "positioning, pricing",
        },
        "barbell-strategy": {
            "title": "Barbell strategy",
            "body": "Put 90% in safe assets and 10% in high-risk bets. Avoid the middle.",
            "tags": "risk, strategy",
        },
        "vulnerability-hooks-outperform-aspirational-hooks": {
            "title": "Vulnerability hooks outperform aspirational hooks by 10x",
            "body": "People engage more with honest struggle than polished success.",
            "tags": "content, marketing",
        },
    }
    for slug, data in atoms.items():
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    # Init DB + index + embed
    conn = open_db(brain_dir / "brain.db")
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings, _deterministic_embed
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    from eureka.core.linker import link_all
    link_all(conn)

    return brain_dir, conn


class FakeLLM:
    """Returns a canned extraction response."""
    def generate(self, prompt):
        return """# Staying broad is underrated because specialists miss adjacent opportunities

Generalists can spot connections across domains that specialists never see. The cost of niching is tunnel vision.

tags: positioning, strategy

---

# Fear of feedback traps you in the identity that needs it most

Avoiding criticism protects a self-image that would benefit most from being challenged.

tags: psychology, growth"""


def test_dump_extracts_atoms(tmp_path):
    """Dump extracts atoms from raw text and writes them to the brain."""
    brain_dir, conn = _seed_brain(tmp_path)
    from eureka.core.dump import process_dump

    result = process_dump(
        raw_text="I think staying broad is underrated. Specialists miss so much. Also I've been avoiding feedback and I think that's holding me back.",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    assert len(result["atoms_extracted"]) == 2
    assert result["atoms_extracted"][0]["slug"] == "staying-broad-is-underrated-because-specialists-miss-adjacent-opportunities"
    assert result["atoms_extracted"][1]["title"].startswith("Fear of feedback")


def test_dump_creates_source_row(tmp_path):
    """Dump creates a source row with type='dump'."""
    brain_dir, conn = _seed_brain(tmp_path)
    from eureka.core.dump import process_dump

    process_dump(
        raw_text="some thoughts",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    row = conn.execute("SELECT * FROM sources WHERE type = 'dump'").fetchone()
    assert row is not None
    assert row["type"] == "dump"
    assert row["atom_count"] == 2


def test_dump_finds_connections(tmp_path):
    """Dump finds connections between new atoms and existing brain."""
    brain_dir, conn = _seed_brain(tmp_path)
    from eureka.core.dump import process_dump

    result = process_dump(
        raw_text="broad vs niche",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    # The "staying broad" atom should connect to "niching down" (same topic, opposing view)
    assert len(result["connections"]) > 0
    slugs_connected = [c["existing_atom"] for c in result["connections"]]
    # At least one connection to an existing atom
    assert any(s in slugs_connected for s in [
        "niching-down-lets-you-charge-100x",
        "barbell-strategy",
        "vulnerability-hooks-outperform-aspirational-hooks",
    ])


def test_dump_finds_molecules_touched(tmp_path):
    """If existing molecules contain atoms near the dump, they're surfaced."""
    brain_dir, conn = _seed_brain(tmp_path)

    # Create a molecule that contains an existing atom
    conn.execute(
        "INSERT INTO molecules (slug, title, eli5, review_status) VALUES (?, ?, ?, 'accepted')",
        ("niche-molecule", "Niche Molecule", "Niching down is powerful"),
    )
    conn.execute(
        "INSERT INTO molecule_atoms (molecule_slug, atom_slug) VALUES (?, ?)",
        ("niche-molecule", "niching-down-lets-you-charge-100x"),
    )
    conn.commit()

    from eureka.core.dump import process_dump
    result = process_dump(
        raw_text="broad vs niche",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    assert len(result["molecules_touched"]) > 0
    assert result["molecules_touched"][0]["slug"] == "niche-molecule"


def test_dump_logs_activity(tmp_path):
    """Dump logs an activity entry."""
    brain_dir, conn = _seed_brain(tmp_path)
    from eureka.core.dump import process_dump

    process_dump(
        raw_text="some thoughts",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    row = conn.execute("SELECT * FROM activity WHERE type = 'dump'").fetchone()
    assert row is not None


def test_dump_returns_correct_envelope_shape(tmp_path):
    """Dump output has the shape specified in SPEC-v3."""
    brain_dir, conn = _seed_brain(tmp_path)
    from eureka.core.dump import process_dump

    result = process_dump(
        raw_text="some thoughts",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    assert "atoms_extracted" in result
    assert "connections" in result
    assert "molecules_touched" in result
    # tensions and gaps come in slice 13
