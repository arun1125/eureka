"""Embeddings — embed text, cache in DB, cosine similarity."""

import math
import sqlite3
import struct
import time
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    """Embed a single text string, return list of floats."""
    model = _get_model()
    vectors = list(model.embed([text]))
    return vectors[0].tolist()


def cosine_sim(vec1: list[float], vec2: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def _pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def ensure_embeddings(conn: sqlite3.Connection, brain_dir: Path) -> None:
    """Embed all atoms and cache vectors in the embeddings table. Idempotent."""
    from eureka.core.db import atom_table
    rows = conn.execute(f"SELECT slug, body FROM {atom_table(conn)}").fetchall()
    existing = {
        r["slug"]
        for r in conn.execute("SELECT slug FROM embeddings").fetchall()
    }

    for row in rows:
        slug = row["slug"]
        if slug in existing:
            continue
        vec = embed_text(row["body"])
        blob = _pack_vector(vec)
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (slug, model, vector, updated) VALUES (?, ?, ?, ?)",
            (slug, MODEL_NAME, blob, time.time()),
        )

    conn.commit()
