"""Slice 6: scorer — IT metric (coherence × novelty × emergence) → 0-100."""

from eureka.core.scorer import score_candidate


def test_score_returns_0_to_100():
    """Score is always in [0, 100]."""
    # Fake embeddings — 3 atoms with known similarities
    embeddings = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.9, 0.1, 0.0],
        "c": [0.8, 0.2, 0.0],
    }
    all_embeddings = embeddings  # brain-wide for typicality
    score = score_candidate(["a", "b", "c"], embeddings, all_embeddings)
    assert 0 <= score <= 100


def test_score_higher_for_diverse_atoms():
    """Atoms that are related but not identical score higher than clones."""
    # Near-identical atoms (low novelty)
    clones = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.99, 0.01, 0.0],
        "c": [0.98, 0.02, 0.0],
    }
    # Related but distinct atoms (good coherence + novelty)
    diverse = {
        "d": [1.0, 0.0, 0.0],
        "e": [0.7, 0.7, 0.0],
        "f": [0.0, 1.0, 0.0],
    }
    all_emb = {**clones, **diverse}
    score_clones = score_candidate(["a", "b", "c"], clones, all_emb)
    score_diverse = score_candidate(["d", "e", "f"], diverse, all_emb)
    assert score_diverse > score_clones


def test_score_zero_for_missing_embeddings():
    """If an atom has no embedding, score is 0."""
    embeddings = {"a": [1.0, 0.0]}
    score = score_candidate(["a", "b", "c"], embeddings, embeddings)
    assert score == 0
