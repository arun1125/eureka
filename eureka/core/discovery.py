"""Discovery — find triangle and V-structure candidates among atoms."""

from __future__ import annotations

import sqlite3
import numpy as np
from eureka.core.embeddings import cosine_sim
from eureka.core.scorer import score_candidate


def _atom_slugs(conn: sqlite3.Connection) -> list[str]:
    """Return all atom slugs from the atoms table."""
    rows = conn.execute("SELECT slug FROM atoms").fetchall()
    return [r["slug"] for r in rows]


def _build_sim_matrix(slugs: list[str], embeddings: dict) -> np.ndarray:
    """Build a pairwise cosine similarity matrix using numpy."""
    n = len(slugs)
    vecs = np.array([embeddings[s] for s in slugs], dtype=np.float32)
    # Normalize
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms
    # Pairwise cosine sim = dot product of normalized vectors
    sim = vecs @ vecs.T
    return sim


def find_triangles(
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
) -> list[dict]:
    """Find triples where all pairwise similarities are in [0.4, 0.85]."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []

    sim = _build_sim_matrix(slugs, embeddings)
    n = len(slugs)
    results = []

    # Pre-compute pairs in range
    in_range = (sim >= 0.4) & (sim <= 0.85)
    np.fill_diagonal(in_range, False)

    for i in range(n):
        # Candidates: atoms j where i-j is in range
        j_candidates = np.where(in_range[i])[0]
        j_candidates = j_candidates[j_candidates > i]
        for j in j_candidates:
            # Candidates: atoms k where i-k and j-k are in range
            k_candidates = np.where(in_range[i] & in_range[j])[0]
            k_candidates = k_candidates[k_candidates > j]
            for k in k_candidates:
                results.append({
                    "atoms": [slugs[i], slugs[j], slugs[k]],
                    "method": "triangle",
                })
                if len(results) >= 50:
                    return results

    return results


def find_v_structures(
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
) -> list[dict]:
    """Find triples (A, B, C) where A↔C > 0.4, B↔C > 0.4, A↔B < 0.4.

    C is the bridge atom.
    """
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []

    sim = _build_sim_matrix(slugs, embeddings)
    n = len(slugs)
    results = []

    high = sim > 0.4
    low = sim < 0.4
    np.fill_diagonal(high, False)
    np.fill_diagonal(low, False)

    # For each potential bridge C, find pairs (A, B) where
    # A↔C > 0.4, B↔C > 0.4, and A↔B < 0.4
    for c in range(n):
        connected = np.where(high[c])[0]
        if len(connected) < 2:
            continue
        for idx_a in range(len(connected)):
            a = connected[idx_a]
            for idx_b in range(idx_a + 1, len(connected)):
                b = connected[idx_b]
                if low[a, b]:
                    results.append({
                        "atoms": [slugs[a], slugs[b], slugs[c]],
                        "bridge": slugs[c],
                        "method": "v-structure",
                    })
                    if len(results) >= 50:
                        return results

    return results


def discover_all(
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
) -> list[dict]:
    """Run all discovery methods, score, and return sorted candidates."""
    candidates = find_triangles(conn, embeddings) + find_v_structures(conn, embeddings)

    for c in candidates:
        candidate_emb = {s: embeddings[s] for s in c["atoms"] if s in embeddings}
        c["score"] = score_candidate(c["atoms"], candidate_emb, embeddings)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates
