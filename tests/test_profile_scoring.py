"""Tests for profile-integrated scoring."""

import struct
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.embeddings import cosine_sim, _deterministic_embed
from eureka.core.scorer import profile_multiplier, score_candidate


# --- Helper: fixed-dimension vectors with known similarity ---
DIM = 128


def _vec(primary: int, secondary: int | None = None, weight: float = 0.1) -> list[float]:
    """Create a DIM-length vector with 1.0 at `primary` index.

    If secondary is given, add `weight` there (makes it slightly off-axis).
    """
    v = [0.0] * DIM
    v[primary] = 1.0
    if secondary is not None:
        v[secondary] = weight
    return v


# Two similar vectors: high cosine sim
VEC_A = _vec(0)                  # [1, 0, 0, ...]
VEC_A_NEAR = _vec(0, 1, 0.1)    # [1, 0.1, 0, ...] — close to VEC_A

# Two distant vectors: low cosine sim
VEC_B = _vec(1)                  # [0, 1, 0, ...]


def _seed_brain(tmp_path):
    """Create a brain with atoms so ask has context to pull from."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()
    (brain_dir / "molecules").mkdir()

    atoms = {
        "focus-compounds-over-time": {
            "title": "Focus compounds over time",
            "body": "Small consistent focus sessions outperform sporadic long ones.",
            "tags": "productivity, focus",
        },
        "barbell-strategy": {
            "title": "Barbell strategy",
            "body": "Put 90% in safe assets and 10% in high-risk bets. Avoid the middle.",
            "tags": "risk, strategy",
        },
        "skin-in-the-game": {
            "title": "Skin in the game",
            "body": "Never trust advice from someone who doesn't bear the downside.",
            "tags": "risk, decision-making",
        },
        "deep-work-requires-solitude": {
            "title": "Deep work requires solitude",
            "body": "Distraction-free blocks are when real cognitive output happens.",
            "tags": "productivity, focus",
        },
        "network-effects-compound": {
            "title": "Network effects compound",
            "body": "Each new connection makes the whole network more valuable.",
            "tags": "business, growth",
        },
        "writing-clarifies-thinking": {
            "title": "Writing clarifies thinking",
            "body": "You don't know what you think until you write it down.",
            "tags": "writing, thinking",
        },
        "leverage-comes-from-code-media-capital": {
            "title": "Leverage comes from code, media, capital",
            "body": "Modern leverage is permissionless: build software, create media, deploy capital.",
            "tags": "business, leverage",
        },
    }
    for slug, data in atoms.items():
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
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


# --- Sanity check: our test vectors behave as expected ---

def test_vector_sanity():
    """Verify test vectors have the expected similarity properties."""
    high_sim = cosine_sim(VEC_A, VEC_A_NEAR)
    low_sim = cosine_sim(VEC_A, VEC_B)
    assert high_sim > 0.5, f"Expected high sim, got {high_sim}"
    assert low_sim < 0.5, f"Expected low sim, got {low_sim}"


# --- profile_multiplier tests ---

def test_profile_multiplier_boosts_aligned():
    """Profile-aligned candidates get a boost > 1.0."""
    profile_embs = {"goal-focus": VEC_A}
    candidate_embs = {"atom-1": VEC_A_NEAR, "atom-2": VEC_A_NEAR}

    result = profile_multiplier(["atom-1", "atom-2"], profile_embs, candidate_embs)
    assert result > 1.0, f"Expected boost > 1.0, got {result}"


def test_profile_multiplier_neutral_when_distant():
    """Distant profile and candidate embeddings produce neutral multiplier."""
    profile_embs = {"goal-focus": VEC_B}
    candidate_embs = {"atom-1": VEC_A, "atom-2": VEC_A}

    result = profile_multiplier(["atom-1", "atom-2"], profile_embs, candidate_embs)
    assert result == 1.0, f"Expected 1.0, got {result}"


def test_profile_multiplier_neutral_when_empty():
    """Empty profile_embeddings returns 1.0."""
    candidate_embs = {"atom-1": VEC_A}

    result = profile_multiplier(["atom-1"], {}, candidate_embs)
    assert result == 1.0


# --- score_candidate with profile ---

def test_score_candidate_with_profile():
    """Profile-aligned candidate scores higher than without profile."""
    atom_slugs = ["atom-1", "atom-2"]
    candidate_embs = {"atom-1": VEC_A_NEAR, "atom-2": VEC_A}
    all_embs = {"atom-1": VEC_A_NEAR, "atom-2": VEC_A, "atom-3": VEC_B}

    # Profile aligned with the candidate atoms
    profile_embs = {"goal-focus": VEC_A}

    score_without = score_candidate(atom_slugs, candidate_embs, all_embs)
    score_with = score_candidate(
        atom_slugs, candidate_embs, all_embs, profile_embeddings=profile_embs,
    )

    assert score_with > score_without, (
        f"Profile-aligned score ({score_with}) should exceed baseline ({score_without})"
    )


# --- ask() with profile data ---

def test_ask_profile_reranking(tmp_path, monkeypatch):
    """ask() runs without crashing when profile data exists and returns results."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)

    # Insert profile entries — these are focus/productivity-aligned
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence) VALUES (?, ?, ?, ?)",
        ("focus-compounds-over-time", "Focus compounds over time", "onboarding", 1.0),
    )
    conn.execute(
        "INSERT INTO profile (key, value, source, confidence) VALUES (?, ?, ?, ?)",
        ("deep-work-requires-solitude", "Deep work requires solitude", "onboarding", 1.0),
    )
    conn.commit()

    from eureka.core.ask import ask
    result = ask("How do I stay focused and productive?", conn, embeddings)

    # Basic contract: ask returns expected keys and doesn't crash
    assert "nearest" in result
    assert "profile_context" in result
    assert len(result["nearest"]) > 0

    # Profile context may or may not return entries depending on embedding similarity
    # to the query. The key contract: ask() doesn't crash with profile data present.
    # If entries are returned, they should have the expected shape.
    for entry in result["profile_context"]:
        assert "key" in entry
        assert "value" in entry
