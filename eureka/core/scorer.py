"""IT metric scorer: coherence x novelty x emergence x diversity x feedback → 0-100."""

from __future__ import annotations

import math
import sqlite3
from itertools import combinations

from eureka.core.embeddings import cosine_sim


def _build_feedback_index(conn: sqlite3.Connection) -> dict:
    """Build a feedback index from reviewed molecules.

    Returns:
        {
            "atom_accept": {slug: count},   # atoms in accepted molecules
            "atom_reject": {slug: count},   # atoms in rejected molecules
            "atom_known":  {slug: count},   # atoms in known/skipped molecules
            "pair_reject": {(s1,s2): count} # atom pairs in rejected molecules
        }
    """
    index = {
        "atom_accept": {},
        "atom_reject": {},
        "atom_known": {},
        "pair_reject": {},
    }

    # Get all reviewed molecules with their atoms
    rows = conn.execute(
        "SELECT m.slug, m.review_status, ma.atom_slug "
        "FROM molecules m "
        "JOIN molecule_atoms ma ON m.slug = ma.molecule_slug "
        "WHERE m.review_status IN ('accepted', 'rejected', 'known')"
    ).fetchall()

    # Group atoms by molecule
    mol_atoms: dict[str, list[str]] = {}
    mol_status: dict[str, str] = {}
    for r in rows:
        mol_atoms.setdefault(r["slug"], []).append(r["atom_slug"])
        mol_status[r["slug"]] = r["review_status"]

    for mol_slug, atoms in mol_atoms.items():
        status = mol_status[mol_slug]
        if status == "accepted":
            for a in atoms:
                index["atom_accept"][a] = index["atom_accept"].get(a, 0) + 1
        elif status == "rejected":
            for a in atoms:
                index["atom_reject"][a] = index["atom_reject"].get(a, 0) + 1
            # Track rejected pairs
            for a1, a2 in combinations(sorted(atoms), 2):
                index["pair_reject"][(a1, a2)] = index["pair_reject"].get((a1, a2), 0) + 1
        elif status == "known":
            for a in atoms:
                index["atom_known"][a] = index["atom_known"].get(a, 0) + 1

    return index


def feedback_multiplier(
    atom_slugs: list[str],
    feedback: dict,
) -> float:
    """Compute a feedback multiplier for a candidate based on review history.

    Returns a multiplier (default 1.0):
        > 1.0  — atoms from accepted molecules (boost)
        < 1.0  — atoms from rejected molecules (penalize)
        = 1.0  — no feedback data
    """
    if not feedback or not any(feedback.values()):
        return 1.0

    accept_hits = sum(feedback["atom_accept"].get(s, 0) for s in atom_slugs)
    reject_hits = sum(feedback["atom_reject"].get(s, 0) for s in atom_slugs)
    known_hits = sum(feedback["atom_known"].get(s, 0) for s in atom_slugs)

    # Check if any atom PAIR was in a rejected molecule (stronger signal)
    sorted_slugs = sorted(atom_slugs)
    pair_reject_hits = sum(
        feedback["pair_reject"].get((a1, a2), 0)
        for a1, a2 in combinations(sorted_slugs, 2)
    )

    # Each accept hit gives +10% boost (capped at 1.5x)
    boost = min(1.0 + accept_hits * 0.1, 1.5)

    # Each reject hit gives -15% penalty
    # Rejected pairs are a stronger signal: -30% each
    penalty = max(1.0 - reject_hits * 0.15 - pair_reject_hits * 0.3, 0.1)

    # Known/skipped: mild penalty (-10% each, user already knows this territory)
    known_penalty = max(1.0 - known_hits * 0.1, 0.5)

    return boost * penalty * known_penalty


def score_candidate(
    atom_slugs: list[str],
    candidate_embeddings: dict[str, list[float]],
    all_embeddings: dict[str, list[float]],
    source_map: dict[str, str] | None = None,
    feedback: dict | None = None,
) -> float:
    """Score a molecule candidate.

    Returns a value in [0, 100].
    source_map: slug → source_title (uses real book sources for diversity scoring).
    feedback: output of _build_feedback_index() — review signals from past molecules.
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

    # --- Feedback: boost/penalize based on review history ---
    fb = feedback_multiplier(atom_slugs, feedback) if feedback else 1.0

    raw = coherence * novelty * (emergence ** 1.5) * diversity * size_bonus * fb
    return max(0, min(round(raw * 100, 1), 100))
