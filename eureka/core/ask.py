"""Ask — graph-aware retrieval over the brain."""

import sqlite3

from eureka.core.embeddings import embed_text, cosine_sim


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

    # --- 1. Nearest atoms by cosine similarity ---
    scored = []
    for slug, vec in embeddings.items():
        sim = cosine_sim(q_vec, vec)
        scored.append({"slug": slug, "similarity": sim})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    nearest = scored[:5]
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

    # --- 4. V-structures (tensions) ---
    tensions = []
    nearest_list = list(nearest_slugs)
    for i in range(len(nearest_list)):
        for j in range(i + 1, len(nearest_list)):
            a, b = nearest_list[i], nearest_list[j]
            # Check if a and b are dissimilar
            if a in embeddings and b in embeddings:
                ab_sim = cosine_sim(embeddings[a], embeddings[b])
                if ab_sim > 0.8:
                    continue  # too similar, not a tension
            # Find shared neighbors (bridges)
            bridges = conn.execute(
                "SELECT e1.target AS bridge FROM edges e1 "
                "JOIN edges e2 ON e1.target = e2.target "
                "WHERE e1.source = ? AND e2.source = ?",
                (a, b),
            ).fetchall()
            for row in bridges:
                bridge = row["bridge"]
                tension_score = 1.0 - ab_sim if a in embeddings and b in embeddings else 0.5
                tensions.append({
                    "a": a,
                    "b": b,
                    "bridge": bridge,
                    "tension_score": round(tension_score, 4),
                })
    tensions.sort(key=lambda x: x["tension_score"], reverse=True)

    return {
        "nearest": nearest,
        "graph_neighbors": graph_neighbors,
        "molecules": molecules,
        "tensions": tensions,
    }
