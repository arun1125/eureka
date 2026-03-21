"""IT metric scorer: coherence x novelty x emergence x diversity → 0-100."""

from __future__ import annotations

import math
from itertools import combinations

from eureka.core.embeddings import cosine_sim


def score_candidate(
    atom_slugs: list[str],
    candidate_embeddings: dict[str, list[float]],
    all_embeddings: dict[str, list[float]],
    source_map: dict[str, str] | None = None,
) -> float:
    """Score a molecule candidate.

    Returns a value in [0, 100].
    source_map: slug → source_title (uses real book sources for diversity scoring).
    """
    if any(slug not in candidate_embeddings for slug in atom_slugs):
        return 0

    vectors = [candidate_embeddings[s] for s in atom_slugs]
    all_vectors = list(all_embeddings.values())
    n_atoms = len(vectors)

    # --- Coherence: average pairwise cosine similarity ---
    if n_atoms < 2:
        coherence = 1.0
    else:
        pairs = list(combinations(vectors, 2))
        coherence = sum(cosine_sim(a, b) for a, b in pairs) / len(pairs)

    # --- Novelty: how different are these atoms from each other? ---
    # Use sqrt(1 - coherence²) but rescale for dense brains
    coh_clamped = max(-1.0, min(1.0, coherence))
    novelty = math.sqrt(1.0 - coh_clamped ** 2)

    # --- Emergence: how unusual is this combination vs random? ---
    def typicality(vec):
        if not all_vectors:
            return 0.0
        return sum(cosine_sim(vec, v) for v in all_vectors) / len(all_vectors)

    avg_atom_typicality = sum(typicality(v) for v in vectors) / n_atoms
    dim = len(vectors[0])
    centroid = [sum(v[d] for v in vectors) / n_atoms for d in range(dim)]
    centroid_typicality = typicality(centroid)

    if centroid_typicality == 0:
        emergence = 1.0
    else:
        emergence = avg_atom_typicality / centroid_typicality

    # --- Source diversity: cross-source molecules are more valuable ---
    diversity = 1.0
    if source_map:
        sources = {source_map.get(s, "unknown") for s in atom_slugs}
        n_sources = len(sources - {"unknown"})
        if n_sources >= 4:
            diversity = 2.0
        elif n_sources >= 3:
            diversity = 1.6
        elif n_sources >= 2:
            diversity = 1.3

    # --- Atom count bonus: larger molecules are harder to find ---
    size_bonus = 1.0
    if n_atoms >= 5:
        size_bonus = 1.3
    elif n_atoms >= 4:
        size_bonus = 1.15

    raw = coherence * novelty * (emergence ** 1.5) * diversity * size_bonus
    return min(round(raw * 100, 1), 100)
