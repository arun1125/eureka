"""IT metric scorer: coherence x novelty x emergence → 0-100."""

from __future__ import annotations

import math
from itertools import combinations

from eureka.core.embeddings import cosine_sim


def score_candidate(
    atom_slugs: list[str],
    candidate_embeddings: dict[str, list[float]],
    all_embeddings: dict[str, list[float]],
) -> float:
    """Score a molecule candidate using the IT metric.

    Returns a value in [0, 100].  Returns 0 if any slug is missing from
    *candidate_embeddings*.
    """
    # Guard: every slug must have an embedding
    if any(slug not in candidate_embeddings for slug in atom_slugs):
        return 0

    vectors = [candidate_embeddings[s] for s in atom_slugs]
    all_vectors = list(all_embeddings.values())

    # --- Coherence: average pairwise cosine similarity ---
    if len(vectors) < 2:
        coherence = 1.0
    else:
        pairs = list(combinations(vectors, 2))
        coherence = sum(cosine_sim(a, b) for a, b in pairs) / len(pairs)

    # --- Novelty: sqrt(1 - coherence²) ---
    coh_clamped = max(-1.0, min(1.0, coherence))
    novelty = math.sqrt(1.0 - coh_clamped ** 2)

    # --- Emergence ---
    # Typicality of a vector = average cosine similarity to ALL vectors
    def typicality(vec: list[float]) -> float:
        if not all_vectors:
            return 0.0
        return sum(cosine_sim(vec, v) for v in all_vectors) / len(all_vectors)

    avg_atom_typicality = sum(typicality(v) for v in vectors) / len(vectors)

    # Centroid of the candidate
    dim = len(vectors[0])
    centroid = [sum(v[d] for v in vectors) / len(vectors) for d in range(dim)]
    centroid_typicality = typicality(centroid)

    if centroid_typicality == 0:
        emergence = 0.0
    else:
        emergence = avg_atom_typicality / centroid_typicality

    raw = coherence * novelty * emergence
    return raw * 100
