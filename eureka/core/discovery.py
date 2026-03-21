"""Discovery — find triangle and V-structure candidates among atoms."""

from __future__ import annotations

import sqlite3
from itertools import combinations

from eureka.core.embeddings import cosine_sim
from eureka.core.scorer import score_candidate


def _atom_slugs(conn: sqlite3.Connection) -> list[str]:
    """Return all atom slugs from the atoms table."""
    rows = conn.execute("SELECT slug FROM atoms").fetchall()
    return [r["slug"] for r in rows]


def find_triangles(
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
) -> list[dict]:
    """Find triples where all pairwise similarities are in [0.4, 0.85]."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    results = []

    for a, b, c in combinations(slugs, 3):
        sim_ab = cosine_sim(embeddings[a], embeddings[b])
        sim_ac = cosine_sim(embeddings[a], embeddings[c])
        sim_bc = cosine_sim(embeddings[b], embeddings[c])

        if all(0.4 <= s <= 0.85 for s in (sim_ab, sim_ac, sim_bc)):
            results.append({
                "atoms": [a, b, c],
                "method": "triangle",
            })

    return results


def find_v_structures(
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
) -> list[dict]:
    """Find triples (A, B, C) where A↔C > 0.4, B↔C > 0.4, A↔B < 0.4.

    C is the bridge atom.
    """
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    results = []

    for a, b, c in combinations(slugs, 3):
        sims = {
            (a, b): cosine_sim(embeddings[a], embeddings[b]),
            (a, c): cosine_sim(embeddings[a], embeddings[c]),
            (b, c): cosine_sim(embeddings[b], embeddings[c]),
        }

        # Try each atom as bridge
        for bridge, low_pair, high_pairs in [
            (c, (a, b), [(a, c), (b, c)]),
            (b, (a, c), [(a, b), (b, c)]),
            (a, (b, c), [(a, b), (a, c)]),
        ]:
            if sims[low_pair] < 0.4 and all(sims[p] > 0.4 for p in high_pairs):
                others = [s for s in (a, b, c) if s != bridge]
                results.append({
                    "atoms": others + [bridge],
                    "bridge": bridge,
                    "method": "v-structure",
                })

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
