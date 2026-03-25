"""Tests for eureka profile — interview, extract, store, retrieve."""

import struct
from pathlib import Path
from eureka.core.db import open_db


def _make_brain(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    conn = open_db(brain_dir / "brain.db")
    return brain_dir, conn


class FakeProfileLLM:
    """Returns canned profile atoms from user answers."""
    def generate(self, prompt):
        return """# My primary goal is to build a YouTube channel about AI tools

I want to create educational content showing people how to use AI tools for real work, not hype.

tags: profile, goals

---

# I tend to over-ideate and under-execute

I spend too long planning and not enough time shipping. The plan becomes a procrastination device.

tags: profile, patterns

---

# I value authenticity over polish

Raw and honest beats slick and empty. People connect with struggle, not perfection.

tags: profile, values"""


def test_get_questions_returns_list():
    """get_questions returns the onboarding interview questions."""
    from eureka.core.profile import get_questions
    questions = get_questions()
    assert isinstance(questions, list)
    assert len(questions) >= 5
    assert all(isinstance(q, str) for q in questions)


def test_process_answers_creates_profile_rows(tmp_path):
    """Processing answers creates rows in the profile table."""
    brain_dir, conn = _make_brain(tmp_path)
    from eureka.core.profile import process_answers

    result = process_answers(
        conn=conn,
        brain_dir=brain_dir,
        answers_text="I'm building a YouTube channel. I over-plan. I value authenticity.",
        llm=FakeProfileLLM(),
    )

    rows = conn.execute("SELECT * FROM profile").fetchall()
    assert len(rows) >= 1  # at least some profile entries extracted


def test_process_answers_creates_atom_files(tmp_path):
    """Profile atoms are written as .md files tagged 'profile'."""
    brain_dir, conn = _make_brain(tmp_path)
    from eureka.core.profile import process_answers

    process_answers(
        conn=conn,
        brain_dir=brain_dir,
        answers_text="I'm building a YouTube channel.",
        llm=FakeProfileLLM(),
    )

    atom_files = list((brain_dir / "atoms").glob("*.md"))
    assert len(atom_files) >= 1

    # Check that at least one has 'profile' in tags
    found_profile_tag = False
    for f in atom_files:
        content = f.read_text()
        if "profile" in content:
            found_profile_tag = True
            break
    assert found_profile_tag, "At least one atom should have 'profile' tag"


def test_process_answers_creates_source_row(tmp_path):
    """Profile processing creates a source with type='profile'."""
    brain_dir, conn = _make_brain(tmp_path)
    from eureka.core.profile import process_answers

    process_answers(
        conn=conn,
        brain_dir=brain_dir,
        answers_text="answers here",
        llm=FakeProfileLLM(),
    )

    row = conn.execute("SELECT * FROM sources WHERE type = 'profile'").fetchone()
    assert row is not None


def test_process_answers_logs_activity(tmp_path):
    """Profile processing logs an activity entry."""
    brain_dir, conn = _make_brain(tmp_path)
    from eureka.core.profile import process_answers

    process_answers(
        conn=conn,
        brain_dir=brain_dir,
        answers_text="answers here",
        llm=FakeProfileLLM(),
    )

    row = conn.execute("SELECT * FROM activity WHERE type = 'profile'").fetchone()
    assert row is not None


def test_get_profile_returns_entries(tmp_path):
    """get_profile returns all profile table entries."""
    brain_dir, conn = _make_brain(tmp_path)
    from eureka.core.profile import process_answers, get_profile

    process_answers(
        conn=conn,
        brain_dir=brain_dir,
        answers_text="answers here",
        llm=FakeProfileLLM(),
    )

    entries = get_profile(conn)
    assert isinstance(entries, list)
    assert len(entries) >= 1
    assert "key" in entries[0]
    assert "value" in entries[0]


def test_get_relevant_profile_filters_by_similarity(tmp_path):
    """get_relevant_profile returns profile entries near a query."""
    brain_dir, conn = _make_brain(tmp_path)
    from eureka.core.profile import process_answers, get_relevant_profile
    from eureka.core.embeddings import embed_text, ensure_embeddings, _deterministic_embed

    process_answers(
        conn=conn,
        brain_dir=brain_dir,
        answers_text="answers here",
        llm=FakeProfileLLM(),
    )

    # Ensure embeddings exist for profile atoms
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)

    # Load embeddings
    embs = {}
    for row in conn.execute("SELECT slug, vector FROM embeddings").fetchall():
        n = len(row["vector"]) // 4
        embs[row["slug"]] = list(struct.unpack(f"{n}f", row["vector"]))

    # Query about content creation — should match YouTube goal
    q_vec = embed_text("how should I approach content creation for YouTube")
    relevant = get_relevant_profile(conn, embs, q_vec)

    assert isinstance(relevant, list)
    # Should return at least the YouTube goal atom
    assert len(relevant) >= 1
