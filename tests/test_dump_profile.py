"""Test that dump output includes profile_context."""

import struct
from eureka.core.db import open_db


def _seed_brain_with_profile(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()

    # One regular atom
    (atoms_dir / "barbell-strategy.md").write_text(
        "# Barbell strategy\n\nPut 90% safe, 10% high-risk.\n\ntags: risk, strategy\n"
    )
    # One profile atom
    (atoms_dir / "my-goal-is-youtube.md").write_text(
        "# My goal is to build a YouTube channel\n\nEducational AI content.\n\ntags: profile, goals\n"
    )

    conn = open_db(brain_dir / "brain.db")
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence, created_at, updated_at) "
        "VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))",
        ("my-goal-is-youtube", "My goal is to build a YouTube channel"),
    )
    conn.commit()

    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings
    ensure_embeddings(conn, brain_dir)
    from eureka.core.linker import link_all
    link_all(conn)

    return brain_dir, conn


class FakeLLM:
    def generate(self, prompt):
        return "# Video content beats text for engagement\n\nPeople retain more from video.\n\ntags: content"


def test_dump_includes_profile_context(tmp_path):
    brain_dir, conn = _seed_brain_with_profile(tmp_path)
    from eureka.core.dump import process_dump

    result = process_dump(
        raw_text="I should focus more on video content",
        conn=conn,
        brain_dir=brain_dir,
        llm=FakeLLM(),
    )

    assert "profile_context" in result
    assert isinstance(result["profile_context"], list)
