"""Linker — compute top-5 cosine-similarity edges per atom."""

import sqlite3
import struct
from datetime import datetime

from eureka.core.embeddings import cosine_sim


def link_all(conn: sqlite3.Connection) -> None:
    """Read all atoms + embeddings, compute top-5 similar neighbours, upsert edges."""
    # Ensure similarity column exists (may not be in original schema)
    try:
        conn.execute("ALTER TABLE edges ADD COLUMN similarity REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

    # Load all embeddings: slug -> vector
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    vectors: dict[str, list[float]] = {}
    for row in rows:
        blob = row["vector"]
        dim = len(blob) // 4
        vec = list(struct.unpack(f"{dim}f", blob))
        vectors[row["slug"]] = vec

    slugs = list(vectors.keys())

    # For each atom, compute similarity to every other, keep top 5
    for slug in slugs:
        sims = []
        for other in slugs:
            if other == slug:
                continue
            sim = cosine_sim(vectors[slug], vectors[other])
            sims.append((other, sim))
        sims.sort(key=lambda x: x[1], reverse=True)
        top5 = sims[:5]

        now = datetime.now().isoformat()
        for target, sim in top5:
            conn.execute(
                "INSERT OR REPLACE INTO edges (source, target, similarity, created_at) VALUES (?, ?, ?, ?)",
                (slug, target, sim, now),
            )

    conn.commit()
