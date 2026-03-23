"""Discovery — find molecule candidates using multiple geometric methods."""

from __future__ import annotations

import random
import sqlite3
import numpy as np
from collections import defaultdict

from eureka.core.embeddings import cosine_sim
from eureka.core.scorer import score_candidate


def _atom_slugs(conn: sqlite3.Connection) -> list[str]:
    from eureka.core.db import atom_table
    rows = conn.execute(f"SELECT slug FROM {atom_table(conn)}").fetchall()
    return [r["slug"] for r in rows]


def _build_sim_matrix(slugs: list[str], embeddings: dict) -> np.ndarray:
    n = len(slugs)
    vecs = np.array([embeddings[s] for s in slugs], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms
    return vecs @ vecs.T


def _build_normed_matrix(slugs: list[str], embeddings: dict):
    vecs = np.array([embeddings[s] for s in slugs], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def _simple_communities(sim: np.ndarray, slugs: list[str], threshold=None) -> dict:
    """Simple greedy community detection from sim matrix."""
    n = len(slugs)
    if threshold is None:
        # Adaptive: use 75th percentile so ~25% of pairs are "same community"
        triu = sim[np.triu_indices(n, k=1)]
        threshold = float(np.percentile(triu, 75))
    assigned = {}
    community_id = 0
    for i in range(n):
        if slugs[i] in assigned:
            continue
        assigned[slugs[i]] = community_id
        for j in range(i + 1, n):
            if slugs[j] not in assigned and sim[i, j] > threshold:
                assigned[slugs[j]] = community_id
        community_id += 1
    return assigned


# --- Method 1: Triangles ---

def find_triangles(conn, embeddings, cap=20):
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []
    sim = _build_sim_matrix(slugs, embeddings)
    results = []
    in_range = (sim >= 0.4) & (sim <= 0.85)
    np.fill_diagonal(in_range, False)
    for i in range(len(slugs)):
        j_cands = np.where(in_range[i])[0]
        j_cands = j_cands[j_cands > i]
        for j in j_cands:
            k_cands = np.where(in_range[i] & in_range[j])[0]
            k_cands = k_cands[k_cands > j]
            for k in k_cands:
                results.append({"atoms": [slugs[i], slugs[j], slugs[k]], "method": "triangle"})
                if len(results) >= cap:
                    return results
    return results


# --- Method 2: V-structures ---

def find_v_structures(conn, embeddings, cap=20):
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []
    sim = _build_sim_matrix(slugs, embeddings)
    # Adaptive thresholds based on the brain's actual similarity distribution
    triu = sim[np.triu_indices(len(slugs), k=1)]
    median_sim = float(np.median(triu))
    low_thresh = max(0.35, median_sim - 0.1)  # bottom quartile
    high_thresh = max(0.45, median_sim - 0.05)
    results = []
    high = sim > high_thresh
    low = sim < low_thresh
    np.fill_diagonal(high, False)
    np.fill_diagonal(low, False)
    for c in range(len(slugs)):
        connected = np.where(high[c])[0]
        if len(connected) < 2:
            continue
        for ia in range(len(connected)):
            a = connected[ia]
            for ib in range(ia + 1, len(connected)):
                b = connected[ib]
                if low[a, b]:
                    results.append({
                        "atoms": [slugs[a], slugs[b], slugs[c]],
                        "bridge": slugs[c],
                        "method": "v-structure",
                    })
                    if len(results) >= cap:
                        return results
    return results


# --- Method 3: Random walk ---

def find_walks(conn, embeddings, n_walks=30, walk_length=6, cap=20):
    """Random walk on the edge graph. Start at a random atom, walk N hops.
    Generates both short (3-atom) and long (4-5 atom) molecules."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []

    # Build adjacency from edges table
    adj = defaultdict(list)
    for row in conn.execute("SELECT source, target FROM edges"):
        s, t = row["source"], row["target"]
        if s in embeddings and t in embeddings:
            adj[s].append(t)
            adj[t].append(s)

    results = []
    seen = set()
    for _ in range(n_walks * 5):
        start = random.choice(slugs)
        current = start
        path = [current]
        for _ in range(walk_length):
            neighbors = adj.get(current, [])
            if not neighbors:
                break
            current = random.choice(neighbors)
            if current not in path:
                path.append(current)

        if len(path) >= 5:
            # Long walk: take 4-5 evenly spaced atoms along the path
            n = len(path)
            indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
            atoms = list(dict.fromkeys(path[i] for i in indices if i < n))  # dedupe preserving order
            if len(atoms) >= 4:
                key = tuple(sorted(atoms))
                if key not in seen:
                    seen.add(key)
                    results.append({"atoms": atoms, "method": "walk"})
                    if len(results) >= cap:
                        return results
        elif len(path) >= 3:
            # Short walk: start, middle, end
            a, b, c = path[0], path[len(path) // 2], path[-1]
            key = tuple(sorted([a, b, c]))
            if key not in seen:
                seen.add(key)
                results.append({"atoms": [a, b, c], "method": "walk"})
                if len(results) >= cap:
                    return results

    return results


# --- Method 4: Bridge atoms ---

def find_bridges(conn, embeddings, cap=20):
    """Atoms that connect two otherwise disconnected communities."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 5:
        return []

    sim = _build_sim_matrix(slugs, embeddings)
    communities = _simple_communities(sim, slugs)

    # Group by community
    comm_members = defaultdict(list)
    for s, c in communities.items():
        comm_members[c].append(s)

    # Find atoms with high similarity to atoms in OTHER communities
    slug_to_idx = {s: i for i, s in enumerate(slugs)}
    results = []
    seen = set()

    for slug in slugs:
        my_comm = communities.get(slug, -1)
        idx = slug_to_idx[slug]
        # Find top neighbor in each other community
        for cid, members in comm_members.items():
            if cid == my_comm or len(members) < 2:
                continue
            member_indices = [slug_to_idx[m] for m in members if m in slug_to_idx]
            sims = sim[idx, member_indices]
            best_local = int(np.argmax(sims))
            best_sim = float(sims[best_local])
            if best_sim > 0.4:
                other = members[best_local]
                # Find another atom from bridge's own community
                my_members = [m for m in comm_members[my_comm] if m != slug]
                if my_members:
                    own_mate = my_members[0]
                    key = tuple(sorted([slug, other, own_mate]))
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "atoms": [own_mate, other, slug],
                            "bridge": slug,
                            "method": "bridge",
                        })
                        if len(results) >= cap:
                            return results

    return results


# --- Method 5: Antipodal ---

def find_antipodal(conn, embeddings, cap=20):
    """Atoms at maximum semantic distance that share a structural path (edge)."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []

    sim = _build_sim_matrix(slugs, embeddings)

    # Build adjacency
    adj = defaultdict(set)
    for row in conn.execute("SELECT source, target FROM edges"):
        s, t = row["source"], row["target"]
        adj[s].add(t)
        adj[t].add(s)

    # Find pairs with LOW similarity but a shared neighbor (structural path)
    results = []
    seen = set()
    n = len(slugs)

    # Adaptive: use bottom 10% of similarity distribution
    triu = sim[np.triu_indices(n, k=1)]
    low_cutoff = float(np.percentile(triu, 15))

    low_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] < low_cutoff:
                low_pairs.append((i, j, float(sim[i, j])))
    low_pairs.sort(key=lambda x: x[2])

    for i, j, s in low_pairs[:200]:
        a, b = slugs[i], slugs[j]
        # Find shared neighbor
        shared = adj.get(a, set()) & adj.get(b, set())
        if shared:
            bridge = list(shared)[0]
            key = tuple(sorted([a, b, bridge]))
            if key not in seen:
                seen.add(key)
                results.append({
                    "atoms": [a, b, bridge],
                    "bridge": bridge,
                    "method": "antipodal",
                })
                if len(results) >= cap:
                    return results

    return results


# --- Method 6: Void (interpolation) ---

def find_voids(conn, embeddings, cap=20):
    """Find semantic gaps between clusters — midpoints with no nearby atoms."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 5:
        return []

    matrix = _build_normed_matrix(slugs, embeddings)
    sim = matrix @ matrix.T
    communities = _simple_communities(sim, slugs)
    slug_to_idx = {s: i for i, s in enumerate(slugs)}

    comm_members = defaultdict(list)
    for s, c in communities.items():
        comm_members[c].append(s)

    comm_ids = [c for c, m in comm_members.items() if len(m) >= 2]
    void_candidates = []

    for ci in range(len(comm_ids)):
        for cj in range(ci + 1, len(comm_ids)):
            members_i = comm_members[comm_ids[ci]][:6]
            members_j = comm_members[comm_ids[cj]][:6]
            for si in members_i:
                vi = matrix[slug_to_idx[si]]
                for sj in members_j:
                    vj = matrix[slug_to_idx[sj]]
                    mid = (vi + vj) / 2.0
                    mid_norm = np.linalg.norm(mid)
                    if mid_norm < 1e-10:
                        continue
                    mid = mid / mid_norm
                    sims_to_mid = matrix @ mid
                    nearest_sim = float(np.max(sims_to_mid))
                    void_radius = 1.0 - nearest_sim
                    pair_sim = float(sim[slug_to_idx[si], slug_to_idx[sj]])
                    if pair_sim < 0.3:
                        continue
                    void_candidates.append({
                        "mid": mid, "void_radius": void_radius,
                        "pair": (si, sj), "gap_score": void_radius * pair_sim,
                    })

    void_candidates.sort(key=lambda v: v["gap_score"], reverse=True)

    # Deduplicate
    unique = []
    for vc in void_candidates:
        dup = False
        for u in unique:
            if np.dot(vc["mid"], u["mid"]) > 0.95:
                dup = True
                break
        if not dup:
            unique.append(vc)
        if len(unique) >= cap:
            break

    # For each void, find boundary atoms
    results = []
    for void in unique:
        sims = matrix @ void["mid"]
        top_indices = np.argsort(-sims)[:3]
        atoms = [slugs[i] for i in top_indices]
        results.append({
            "atoms": atoms,
            "method": "void",
            "void_radius": round(void["void_radius"], 4),
            "seed_pair": list(void["pair"]),
        })

    return results


# --- Method 7: Cluster-boundary ---

def find_cluster_boundary(conn, embeddings, cap=20):
    """Atoms at the edge of their community, near another community."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 5:
        return []

    sim = _build_sim_matrix(slugs, embeddings)
    communities = _simple_communities(sim, slugs)
    slug_to_idx = {s: i for i, s in enumerate(slugs)}

    comm_members = defaultdict(list)
    for s, c in communities.items():
        comm_members[c].append(s)

    results = []
    seen = set()

    for slug in slugs:
        my_comm = communities.get(slug, -1)
        idx = slug_to_idx[slug]
        my_members = [m for m in comm_members[my_comm] if m != slug]
        if not my_members:
            continue

        # Average sim to own community
        own_sims = [sim[idx, slug_to_idx[m]] for m in my_members]
        avg_own = np.mean(own_sims)

        # Find highest sim to any other community
        for cid, members in comm_members.items():
            if cid == my_comm:
                continue
            other_sims = [sim[idx, slug_to_idx[m]] for m in members if m in slug_to_idx]
            if not other_sims:
                continue
            max_other = max(other_sims)
            best_other = members[np.argmax(other_sims)]

            # Boundary = close to other community relative to own
            if max_other > avg_own * 0.8 and max_other > 0.35:
                own_mate = my_members[np.argmax([sim[idx, slug_to_idx[m]] for m in my_members])]
                key = tuple(sorted([slug, best_other, own_mate]))
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "atoms": [slug, best_other, own_mate],
                        "method": "cluster-boundary",
                    })
                    if len(results) >= cap:
                        return results

    return results


# --- Method 8: Residual (unexploited atoms) ---

def find_residuals(conn, embeddings, cap=20):
    """Atoms with few edges relative to their potential — underconnected."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if len(slugs) < 3:
        return []

    # Count edges per atom
    edge_count = defaultdict(int)
    for row in conn.execute("SELECT source, target FROM edges"):
        edge_count[row["source"]] += 1
        edge_count[row["target"]] += 1

    # Find atoms with fewest edges
    atom_edges = [(s, edge_count.get(s, 0)) for s in slugs]
    atom_edges.sort(key=lambda x: x[1])

    sim = _build_sim_matrix(slugs, embeddings)
    slug_to_idx = {s: i for i, s in enumerate(slugs)}
    results = []
    seen = set()

    # For each underconnected atom, pair it with its most similar atoms
    for slug, count in atom_edges[:cap * 2]:
        idx = slug_to_idx[slug]
        sims = sim[idx].copy()
        sims[idx] = -1  # exclude self
        top2 = np.argsort(-sims)[:2]
        atoms = [slug] + [slugs[i] for i in top2]
        key = tuple(sorted(atoms))
        if key not in seen:
            seen.add(key)
            results.append({
                "atoms": atoms,
                "method": "residual",
                "edge_count": count,
            })
            if len(results) >= cap:
                return results

    return results


# --- Per-atom discovery (for interactive Idea Lab) ---

def discover_from_atom(conn, embeddings, start_slug: str, method: str, cap: int = 10):
    """Build candidates around a specific starting atom."""
    slugs = [s for s in _atom_slugs(conn) if s in embeddings]
    if start_slug not in embeddings or len(slugs) < 3:
        return []

    sim = _build_sim_matrix(slugs, embeddings)
    slug_to_idx = {s: i for i, s in enumerate(slugs)}
    start_idx = slug_to_idx[start_slug]

    # Build adjacency
    adj = defaultdict(list)
    for row in conn.execute("SELECT source, target FROM edges"):
        s, t = row["source"], row["target"]
        if s in embeddings and t in embeddings:
            adj[s].append(t)
            adj[t].append(s)

    results = []
    seen = set()

    if method == "triangle":
        # Find pairs (b, c) where start-b, start-c, and b-c all have decent similarity
        sims_from_start = sim[start_idx]
        # Get atoms with moderate similarity to start (not too close, not too far)
        candidates_idx = [j for j in range(len(slugs)) if j != start_idx and 0.4 <= sims_from_start[j] <= 0.85]
        for j in candidates_idx:
            for k in candidates_idx:
                if k <= j:
                    continue
                if 0.4 <= sim[j, k] <= 0.85:
                    atoms = [start_slug, slugs[j], slugs[k]]
                    key = tuple(sorted(atoms))
                    if key not in seen:
                        seen.add(key)
                        results.append({"atoms": atoms, "method": "triangle"})
                        if len(results) >= cap:
                            return results

    elif method == "walk":
        for _ in range(cap * 10):
            current = start_slug
            path = [current]
            for _ in range(5):
                neighbors = adj.get(current, [])
                if not neighbors:
                    break
                current = random.choice(neighbors)
                if current not in path:
                    path.append(current)
            if len(path) >= 3:
                atoms = [path[0], path[len(path) // 2], path[-1]]
                key = tuple(sorted(atoms))
                if key not in seen:
                    seen.add(key)
                    results.append({"atoms": atoms, "method": "walk"})
                    if len(results) >= cap:
                        return results

    elif method == "antipodal":
        # Find atoms most distant from start that share a neighbor
        sims_from_start = sim[start_idx]
        # Sort by lowest similarity
        distant = np.argsort(sims_from_start)
        for j in distant:
            if slugs[j] == start_slug:
                continue
            other = slugs[j]
            # Find shared neighbor
            shared = set(adj.get(start_slug, [])) & set(adj.get(other, []))
            if shared:
                bridge = list(shared)[0]
                atoms = [start_slug, other, bridge]
                key = tuple(sorted(atoms))
                if key not in seen:
                    seen.add(key)
                    results.append({"atoms": atoms, "bridge": bridge, "method": "antipodal"})
                    if len(results) >= cap:
                        return results

    elif method == "cluster-boundary":
        # Find atoms from OTHER communities that are closest to start
        communities = _simple_communities(sim, slugs)
        my_comm = communities.get(start_slug, -1)
        comm_members = defaultdict(list)
        for s, c in communities.items():
            comm_members[c].append(s)

        sims_from_start = sim[start_idx]
        for cid, members in comm_members.items():
            if cid == my_comm:
                continue
            # Find closest member of other community
            member_sims = [(m, sims_from_start[slug_to_idx[m]]) for m in members if m in slug_to_idx]
            member_sims.sort(key=lambda x: x[1], reverse=True)
            if not member_sims:
                continue
            other = member_sims[0][0]
            # Pick a mate from start's own community
            my_mates = [m for m in comm_members[my_comm] if m != start_slug]
            if my_mates:
                mate_sims = [(m, sims_from_start[slug_to_idx[m]]) for m in my_mates]
                mate_sims.sort(key=lambda x: x[1], reverse=True)
                mate = mate_sims[0][0]
                atoms = [start_slug, other, mate]
                key = tuple(sorted(atoms))
                if key not in seen:
                    seen.add(key)
                    results.append({"atoms": atoms, "method": "cluster-boundary"})
                    if len(results) >= cap:
                        return results

    # Fallback: if method-specific logic returned nothing, use nearest neighbors
    if not results:
        sims_from_start = sim[start_idx].copy()
        sims_from_start[start_idx] = -1
        top = np.argsort(-sims_from_start)
        for i in range(0, min(len(top) - 1, cap * 2), 2):
            j, k = int(top[i]), int(top[i + 1])
            atoms = [start_slug, slugs[j], slugs[k]]
            key = tuple(sorted(atoms))
            if key not in seen:
                seen.add(key)
                results.append({"atoms": atoms, "method": method})
                if len(results) >= cap:
                    break

    return results


# --- Orchestrator ---

def discover_all(conn, embeddings):
    """Run all discovery methods, score, and return sorted candidates."""
    candidates = (
        find_triangles(conn, embeddings)
        + find_v_structures(conn, embeddings)
        + find_walks(conn, embeddings)
        + find_bridges(conn, embeddings)
        + find_antipodal(conn, embeddings)
        + find_voids(conn, embeddings)
        + find_cluster_boundary(conn, embeddings)
        + find_residuals(conn, embeddings)
    )

    # Build source map from atoms table (real book sources)
    from eureka.core.db import atom_table, atom_source_expr
    _atbl = atom_table(conn)
    _src_expr = atom_source_expr(conn)
    source_map = {}
    try:
        rows = conn.execute(f"SELECT slug, {_src_expr} AS source_title FROM {_atbl} WHERE {_src_expr} IS NOT NULL").fetchall()
        for r in rows:
            source_map[r["slug"]] = r["source_title"]
    except Exception:
        pass  # source_title column may not exist in older brains

    # Build feedback index from reviewed molecules
    from eureka.core.scorer import _build_feedback_index
    feedback = _build_feedback_index(conn)

    for c in candidates:
        atom_slugs = [a if isinstance(a, str) else a["slug"] for a in c["atoms"]]
        candidate_emb = {s: embeddings[s] for s in atom_slugs if s in embeddings}
        c["score"] = score_candidate(atom_slugs, candidate_emb, embeddings, source_map, feedback)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates
