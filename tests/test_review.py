"""Slice 8: eureka review — accept/reject molecules."""

import json
import shutil
from io import StringIO
from pathlib import Path
from datetime import datetime

from eureka.core.db import open_db
from eureka.core.index import rebuild_index

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_brain_with_molecule(tmp_path):
    """Create a brain with a pending molecule for review."""
    brain_dir = tmp_path / "mybrain"
    atoms_dir = brain_dir / "atoms"
    mol_dir = brain_dir / "molecules"
    atoms_dir.mkdir(parents=True)
    mol_dir.mkdir()

    # Add some atoms
    for f in FIXTURES.glob("*.md"):
        shutil.copy(f, atoms_dir / f.name)

    conn = open_db(brain_dir)
    rebuild_index(conn, brain_dir)

    # Insert a fake pending molecule
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO molecules (slug, method, score, review_status, eli5, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("stress-and-subtraction-build-antifragility", "triangle", 72.5, "pending",
         "Getting rid of bad stuff makes you stronger than adding good stuff.",
         "Hormesis and via negativa both achieve robustness through subtraction.",
         now)
    )
    conn.commit()

    # Write the molecule .md file
    (mol_dir / "stress-and-subtraction-build-antifragility.md").write_text(
        "# Stress and subtraction build antifragility\n\n"
        "Hormesis and via negativa both achieve robustness through subtraction.\n"
    )

    return brain_dir, conn


def test_review_accept(tmp_path):
    """Accepting a molecule updates review_status and logs the review."""
    brain_dir, conn = _setup_brain_with_molecule(tmp_path)

    from eureka.core.review import accept_molecule
    accept_molecule(conn, "stress-and-subtraction-build-antifragility", brain_dir)

    mol = conn.execute("SELECT review_status FROM molecules WHERE slug = ?",
                       ("stress-and-subtraction-build-antifragility",)).fetchone()
    assert mol["review_status"] == "accepted"

    # Review logged
    reviews = conn.execute("SELECT decision FROM reviews WHERE slug = ?",
                           ("stress-and-subtraction-build-antifragility",)).fetchall()
    assert len(reviews) == 1
    assert reviews[0]["decision"] == "accepted"

    # .md file still exists
    assert (brain_dir / "molecules" / "stress-and-subtraction-build-antifragility.md").exists()


def test_review_reject(tmp_path):
    """Rejecting a molecule deletes it and logs the review."""
    brain_dir, conn = _setup_brain_with_molecule(tmp_path)

    from eureka.core.review import reject_molecule
    reject_molecule(conn, "stress-and-subtraction-build-antifragility", brain_dir)

    mol = conn.execute("SELECT review_status FROM molecules WHERE slug = ?",
                       ("stress-and-subtraction-build-antifragility",)).fetchone()
    assert mol["review_status"] == "rejected"

    # Review logged
    reviews = conn.execute("SELECT decision FROM reviews WHERE slug = ?",
                           ("stress-and-subtraction-build-antifragility",)).fetchall()
    assert len(reviews) == 1
    assert reviews[0]["decision"] == "rejected"

    # .md file deleted
    assert not (brain_dir / "molecules" / "stress-and-subtraction-build-antifragility.md").exists()


def test_review_already_reviewed(tmp_path):
    """Reviewing an already-reviewed molecule returns error."""
    brain_dir, conn = _setup_brain_with_molecule(tmp_path)

    from eureka.core.review import accept_molecule, ReviewError
    accept_molecule(conn, "stress-and-subtraction-build-antifragility", brain_dir)

    # Second review should raise
    try:
        accept_molecule(conn, "stress-and-subtraction-build-antifragility", brain_dir)
        assert False, "Should have raised ReviewError"
    except ReviewError:
        pass


def test_review_nonexistent_slug(tmp_path):
    """Reviewing a nonexistent slug returns error."""
    brain_dir, conn = _setup_brain_with_molecule(tmp_path)

    from eureka.core.review import accept_molecule, ReviewError
    try:
        accept_molecule(conn, "nonexistent-slug", brain_dir)
        assert False, "Should have raised ReviewError"
    except ReviewError:
        pass


def test_review_cli_accept(tmp_path, monkeypatch):
    """eureka review <slug> yes works via CLI."""
    brain_dir, conn = _setup_brain_with_molecule(tmp_path)
    conn.close()
    (brain_dir / "brain.json").write_text("{}")

    from eureka.commands import review as review_mod

    buf = StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    review_mod.run_review("stress-and-subtraction-build-antifragility", "yes", str(brain_dir))

    output = json.loads(buf.getvalue().strip())
    assert output["ok"] is True
    assert output["command"] == "review"
    assert output["data"]["decision"] == "accepted"
