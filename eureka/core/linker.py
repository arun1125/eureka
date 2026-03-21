"""Linker — compute top-N cosine-similarity edges per atom (numpy vectorized)."""

import sqlite3
import numpy as np
from datetime import datetime

from eureka.core.embeddings import _unpack_vector


def link_all(conn: sqlite3.Connection, top_n: int = 10) -> None:
    """Read all embeddings, compute top-N neighbours per atom, upsert edges."""
    try:
        conn.execute("ALTER TABLE edges ADD COLUMN similarity REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    if not rows:
        return

    slugs = [r["slug"] for r in rows]
    vecs = np.array([_unpack_vector(r["vector"]) for r in rows], dtype=np.float32)

    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms

    sim = vecs @ vecs.T
    np.fill_diagonal(sim, -1)

    now = datetime.now().isoformat()
    conn.execute("DELETE FROM edges")

    for i, slug in enumerate(slugs):
        top_indices = np.argsort(-sim[i])[:top_n]
        for j in top_indices:
            conn.execute(
                "INSERT OR IGNORE INTO edges (source, target, similarity, created_at) VALUES (?, ?, ?, ?)",
                (slug, slugs[int(j)], round(float(sim[i, int(j)]), 4), now),
            )

    conn.commit()
