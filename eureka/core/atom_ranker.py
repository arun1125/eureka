"""Atom ranker — score atoms by connectivity, molecule participation, and feedback."""

from __future__ import annotations

import sqlite3
from itertools import combinations

from eureka.core.db import atom_table
from eureka.core.embeddings import cosine_sim, _unpack_vector


def rank_atoms(conn: sqlite3.Connection) -> list[dict]:
    """Score and rank all atoms. Returns list sorted by score descending.

    Each entry: {slug, score, signals: {connectivity, molecule_value, bridge, untapped}}
    """
    _atbl = atom_table(conn)
    slugs = [r["slug"] for r in conn.execute(f"SELECT slug FROM {_atbl}").fetchall()]
    if not slugs:
        return []

    slug_set = set(slugs)

    # --- Signal 1: Connectivity (edge count, normalized) ---
    edge_counts: dict[str, int] = {s: 0 for s in slugs}
    for r in conn.execute("SELECT source, target FROM edges"):
        if r["source"] in slug_set:
            edge_counts[r["source"]] = edge_counts.get(r["source"], 0) + 1
        if r["target"] in slug_set:
            edge_counts[r["target"]] = edge_counts.get(r["target"], 0) + 1
    max_edges = max(edge_counts.values()) if edge_counts else 1
    max_edges = max(max_edges, 1)

    # --- Signal 2: Molecule value (weighted by review status) ---
    mol_value: dict[str, float] = {s: 0.0 for s in slugs}
    mol_rows = conn.execute(
        "SELECT ma.atom_slug, m.review_status, m.score "
        "FROM molecule_atoms ma "
        "JOIN molecules m ON ma.molecule_slug = m.slug"
    ).fetchall()
    for r in mol_rows:
        slug = r["atom_slug"]
        if slug not in slug_set:
            continue
        status = r["review_status"]
        mol_score = r["score"] or 0
        if status == "accepted":
            mol_value[slug] += 1.0 + mol_score / 100  # accepted = strong signal
        elif status == "rejected":
            mol_value[slug] -= 0.5  # rejected = negative signal
        elif status == "known":
            mol_value[slug] += 0.3  # known = mildly positive (user recognizes it)
        else:  # pending
            mol_value[slug] += 0.2  # pending = weak positive (system found it interesting)

    max_mol = max(abs(v) for v in mol_value.values()) if mol_value else 1
    max_mol = max(max_mol, 1)

    # --- Signal 3: Bridge score (connects different tag communities) ---
    # Get tags per atom
    atom_tags: dict[str, set[str]] = {s: set() for s in slugs}
    tag_rows = conn.execute(
        "SELECT nt.slug, t.name FROM note_tags nt JOIN tags t ON nt.tag_id = t.id"
    ).fetchall()
    for r in tag_rows:
        if r["slug"] in slug_set:
            atom_tags[r["slug"]].add(r["name"])

    # Bridge = neighbors have different tags than you
    neighbors: dict[str, set[str]] = {s: set() for s in slugs}
    for r in conn.execute("SELECT source, target FROM edges"):
        if r["source"] in slug_set and r["target"] in slug_set:
            neighbors[r["source"]].add(r["target"])
            neighbors[r["target"]].add(r["source"])

    bridge_scores: dict[str, float] = {}
    for slug in slugs:
        my_tags = atom_tags.get(slug, set())
        if not my_tags or not neighbors.get(slug):
            bridge_scores[slug] = 0.0
            continue
        foreign_neighbor_count = 0
        for n in neighbors[slug]:
            n_tags = atom_tags.get(n, set())
            if n_tags and not (my_tags & n_tags):  # no tag overlap
                foreign_neighbor_count += 1
        bridge_scores[slug] = foreign_neighbor_count / len(neighbors[slug]) if neighbors[slug] else 0.0

    # --- Signal 4: Untapped potential (connected but not in any molecule) ---
    atoms_in_molecules = set(
        r["atom_slug"] for r in conn.execute("SELECT DISTINCT atom_slug FROM molecule_atoms").fetchall()
    )
    untapped: dict[str, float] = {}
    for slug in slugs:
        if slug in atoms_in_molecules:
            untapped[slug] = 0.0  # already exploited
        else:
            # Score by how connected it is — more edges = more potential
            untapped[slug] = edge_counts.get(slug, 0) / max_edges

    # --- Combine signals ---
    results = []
    for slug in slugs:
        connectivity = edge_counts.get(slug, 0) / max_edges
        mol_val = mol_value.get(slug, 0) / max_mol
        bridge = bridge_scores.get(slug, 0)
        untap = untapped.get(slug, 0)

        # Weighted combination
        score = (
            connectivity * 25      # 25% connectivity
            + mol_val * 30          # 30% molecule participation + feedback
            + bridge * 25           # 25% bridge between communities
            + untap * 20            # 20% untapped potential
        )

        results.append({
            "slug": slug,
            "score": round(score, 1),
            "signals": {
                "connectivity": round(connectivity, 3),
                "molecule_value": round(mol_val, 3),
                "bridge": round(bridge, 3),
                "untapped": round(untap, 3),
            },
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
