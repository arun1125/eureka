"""Linker — compute top-N cosine-similarity edges per atom (numpy vectorized)."""

import sqlite3
import numpy as np
from datetime import datetime

from eureka.core.embeddings import _unpack_vector

DEFAULT_TOP_N = 5
DEFAULT_MIN_SIMILARITY = 0.65


def link_all(
    conn: sqlite3.Connection,
    top_n: int = DEFAULT_TOP_N,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> int:
    """Read all embeddings, keep top-N neighbours per atom above min_similarity.

    Returns the number of edges created.
    """
    try:
        conn.execute("ALTER TABLE edges ADD COLUMN similarity REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    if not rows:
        return 0

    slugs = [r["slug"] for r in rows]
    vecs = np.array([_unpack_vector(r["vector"]) for r in rows], dtype=np.float32)

    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms

    sim = vecs @ vecs.T
    np.fill_diagonal(sim, -1)

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM edges")

    edge_count = 0
    for i, slug in enumerate(slugs):
        top_indices = np.argsort(-sim[i])[:top_n]
        for j in top_indices:
            j = int(j)
            if j == i:
                continue
            similarity = float(sim[i, j])
            if similarity < min_similarity:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO edges (source, target, similarity, created_at) VALUES (?, ?, ?, ?)",
                (slug, slugs[j], round(similarity, 4), now),
            )
            edge_count += 1

    conn.commit()
    return edge_count
