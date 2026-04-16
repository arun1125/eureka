"""Ask — graph-aware retrieval over the brain."""

import sqlite3

from eureka.core.embeddings import embed_text, cosine_sim
from eureka.core.profile import get_relevant_profile


def ask(
    question: str,
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
) -> dict:
    """Graph-aware retrieval for a question.

    1. Embed the question
    2. Find 5 nearest atoms by cosine similarity
    3. Walk 1 hop via edges table
    4. Find molecules containing retrieved atoms
    5. Find V-structures (tensions) near the question

    Returns dict with nearest, graph_neighbors, molecules, tensions.
    """
    q_vec = embed_text(question)

    # --- 0. Profile embeddings (needed for re-ranking) ---
    profile_rows = conn.execute("SELECT key, value FROM profile").fetchall()
    profile_vecs = {}
    for row in profile_rows:
        slug = row["key"]
        if slug in embeddings:
            profile_vecs[slug] = embeddings[slug]

    # --- 1. Nearest atoms by cosine similarity ---
    scored = []
    for slug, vec in embeddings.items():
        sim = cosine_sim(q_vec, vec)
        scored.append({"slug": slug, "similarity": sim})
    scored.sort(key=lambda x: x["similarity"], reverse=True)

    # Take top 10, re-rank by blending similarity with profile relevance, then take top 5
    top_candidates = scored[:10]
    if profile_vecs:
        profile_vec_list = list(profile_vecs.values())
        for item in top_candidates:
            slug = item["slug"]
            if slug in embeddings:
                max_profile_sim = max(cosine_sim(embeddings[slug], pv) for pv in profile_vec_list)
                # Scale profile similarity to 0-0.1 range
                profile_boost = max(0.0, min(max_profile_sim, 1.0)) * 0.1
            else:
                profile_boost = 0.0
            item["final_score"] = item["similarity"] * 0.9 + profile_boost * 0.1
        top_candidates.sort(key=lambda x: x["final_score"], reverse=True)

    nearest = top_candidates[:5]
    nearest_slugs = {item["slug"] for item in nearest}

    # --- 2. Graph neighbors (1 hop) ---
    graph_neighbors = []
    for item in nearest:
        slug = item["slug"]
        rows = conn.execute(
            "SELECT target FROM edges WHERE source = ? "
            "UNION SELECT source FROM edges WHERE target = ?",
            (slug, slug),
        ).fetchall()
        for row in rows:
            neighbor = row[0]
            if neighbor not in nearest_slugs:
                sim = cosine_sim(q_vec, embeddings[neighbor]) if neighbor in embeddings else 0.0
                graph_neighbors.append({
                    "slug": neighbor,
                    "via": slug,
                    "similarity": sim,
                })
    # Deduplicate by slug, keep highest similarity
    seen = {}
    for gn in graph_neighbors:
        key = gn["slug"]
        if key not in seen or gn["similarity"] > seen[key]["similarity"]:
            seen[key] = gn
    graph_neighbors = sorted(seen.values(), key=lambda x: x["similarity"], reverse=True)

    # --- 3. Molecules containing retrieved atoms ---
    all_retrieved = nearest_slugs | {gn["slug"] for gn in graph_neighbors}
    molecules = []
    if all_retrieved:
        placeholders = ",".join("?" for _ in nearest_slugs)
        rows = conn.execute(
            f"SELECT DISTINCT m.slug, m.eli5, m.score "
            f"FROM molecules m "
            f"JOIN molecule_atoms ma ON m.slug = ma.molecule_slug "
            f"WHERE ma.atom_slug IN ({placeholders})",
            list(nearest_slugs),
        ).fetchall()
        for row in rows:
            molecules.append({
                "slug": row["slug"],
                "eli5": row["eli5"],
                "score": row["score"],
            })

    # --- 4. V-structures (tensions) — top 5 only ---
    tensions = []
    nearest_list = list(nearest_slugs)
    for i in range(len(nearest_list)):
        for j in range(i + 1, len(nearest_list)):
            a, b = nearest_list[i], nearest_list[j]
            if a in embeddings and b in embeddings:
                ab_sim = cosine_sim(embeddings[a], embeddings[b])
                if ab_sim > 0.75:
                    continue  # too similar, not a real tension
                if ab_sim > 0.5:
                    continue  # moderately similar — agreement, not tension
            else:
                continue
            # Find shared neighbors (bridges) — only keep the best bridge per pair
            bridges = conn.execute(
                "SELECT e1.target AS bridge FROM edges e1 "
                "JOIN edges e2 ON e1.target = e2.target "
                "WHERE e1.source = ? AND e2.source = ?",
                (a, b),
            ).fetchall()
            if bridges:
                bridge = bridges[0]["bridge"]
                tension_score = 1.0 - ab_sim
                tensions.append({
                    "a": a,
                    "b": b,
                    "bridge": bridge,
                    "tension_score": round(tension_score, 4),
                })
    tensions.sort(key=lambda x: x["tension_score"], reverse=True)
    tensions = tensions[:5]

    # --- 5. Profile context ---
    profile_entries = get_relevant_profile(conn, embeddings, q_vec)
    profile_context = [{"key": e["key"], "value": e["value"]} for e in profile_entries]

    # --- 6. Reframes from V-structures (top 3, with titles) ---
    # Load titles for reframe readability
    from eureka.core.db import atom_table, atom_title_expr
    _atbl = atom_table(conn)
    _title_expr = atom_title_expr(conn)
    _title_cache = {}
    def _get_title(slug):
        if slug not in _title_cache:
            row = conn.execute(f"SELECT {_title_expr} AS title FROM {_atbl} WHERE slug = ?", (slug,)).fetchone()
            _title_cache[slug] = row["title"] if row else slug.replace("-", " ")
        return _title_cache[slug]

    reframes = []
    for t in tensions[:3]:
        a_title = _get_title(t["a"])
        b_title = _get_title(t["b"])
        bridge_title = _get_title(t["bridge"])
        reframes.append({
            "v_structure": {"a": t["a"], "b": t["b"], "bridge": t["bridge"]},
            "reframe": f"What if the question isn't \"{a_title}\" vs \"{b_title}\", but how \"{bridge_title}\" makes both true?",
        })

    # --- 7. Action suggestions from profile goals ---
    action_suggestions = []
    for entry in profile_context:
        goal_words = {w.lower() for w in entry["value"].split() if len(w) > 2}
        covered = False
        for slug in embeddings:
            slug_words = {w.lower() for w in slug.split("-") if len(w) > 2}
            if len(goal_words & slug_words) >= 2:
                covered = True
                break
        if not covered:
            action_suggestions.append({
                "suggestion": f"Your goal '{entry['value']}' has thin coverage in your brain. Consider ingesting a source on this topic.",
            })

    # --- 8. Pushback ---
    # Note: pushback on ask is empty for now. Cosine similarity alone can't
    # distinguish "agrees with query" from "contradicts query" — both land in
    # the 0.5-0.85 band. Pushback works on dump (where we have extracted atoms
    # to compare) but not on freeform questions without an LLM to assess
    # directionality. This will be addressed when we add LLM-assisted
    # contradiction detection.
    pushback = []

    return {
        "nearest": nearest,
        "graph_neighbors": graph_neighbors,
        "molecules": molecules,
        "tensions": tensions,
        "profile_context": profile_context,
        "reframes": reframes,
        "action_suggestions": action_suggestions,
        "pushback": pushback,
    }
