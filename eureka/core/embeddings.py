"""Embeddings — embed text via Gemini Embedding 001, cache in DB, cosine similarity.

Uses Gemini Embedding 001 (3072-dim, #1 MTEB). Requires GEMINI_API_KEY.
"""

import json
import math
import os
import sqlite3
import struct
import sys
import time
from pathlib import Path

GEMINI_MODEL = "gemini-embedding-001"


def _load_env_from_brain_dir(brain_dir: Path) -> None:
    """Load .env from brain directory into os.environ (for GEMINI_API_KEY etc.)."""
    env_path = brain_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def embed_text(text: str) -> list[float]:
    """Embed a single text string via Gemini, return list of floats."""
    from eureka.core.embeddings_gemini import embed_text as gemini_embed
    return gemini_embed(text)


def get_model_name() -> str:
    return GEMINI_MODEL


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


def _deterministic_embed(text: str) -> list[float]:
    """Word-frequency embedding for tests. Deterministic, produces meaningful
    similarity between texts that share words. Not for production."""
    # Build a stable vocabulary from the text's words
    words = text.lower().split()
    # Use a fixed 128-dim space. Each word hashes to a dimension.
    import hashlib
    dim = 128
    vec = [0.0] * dim
    for w in words:
        idx = int(hashlib.md5(w.encode()).hexdigest(), 16) % dim
        vec[idx] += 1.0
    # Add a small unique component so identical-word-set texts aren't equal
    h = hashlib.sha256(text.encode()).digest()
    for i in range(min(dim, len(h))):
        vec[i] += (h[i] - 128) / 1280.0
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else vec


def ensure_embeddings(conn: sqlite3.Connection, brain_dir: Path,
                      force: bool = False, embed_fn=None) -> None:
    """Embed all atoms and cache vectors in the embeddings table.

    If force=True, re-embeds everything (use when switching models).
    Otherwise idempotent — skips atoms that already have embeddings.

    Args:
        embed_fn: Optional callable(text) -> list[float]. If provided, uses this
                  instead of Gemini API. Useful for tests.
    """
    from eureka.core.db import atom_table, transaction

    # Load .env so GEMINI_API_KEY is available
    _load_env_from_brain_dir(brain_dir)
    model_name = get_model_name()

    if force:
        conn.execute("DELETE FROM embeddings")
        conn.commit()
        print(f"Cleared old embeddings. Re-embedding with {model_name}...",
              file=sys.stderr, flush=True)

    rows = conn.execute(f"SELECT slug, body FROM {atom_table(conn)}").fetchall()
    existing = {
        r["slug"]
        for r in conn.execute("SELECT slug FROM embeddings WHERE model = ?",
                              (model_name,)).fetchall()
    }

    to_embed = [r for r in rows if r["slug"] not in existing]
    if not to_embed:
        return

    _embed = embed_fn or embed_text

    print(f"Embedding {len(to_embed)} atoms with {model_name}...",
          file=sys.stderr, flush=True)

    # Batch path (5+ atoms, only when using Gemini — not custom embed_fn)
    if embed_fn is None and len(to_embed) >= 5:
        from eureka.core.embeddings_gemini import embed_batch
        texts = [row["body"] for row in to_embed]
        vectors = embed_batch(texts)
        with transaction(conn):
            for row, vec in zip(to_embed, vectors):
                blob = _pack_vector(vec)
                conn.execute(
                    "INSERT OR REPLACE INTO embeddings (slug, model, vector, updated) VALUES (?, ?, ?, ?)",
                    (row["slug"], model_name, blob, time.time()),
                )
        print(f"  Done. {len(to_embed)} atoms embedded (batch).", file=sys.stderr, flush=True)
        return

    # Sequential path
    for i, row in enumerate(to_embed):
        vec = _embed(row["body"])
        blob = _pack_vector(vec)
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (slug, model, vector, updated) VALUES (?, ?, ?, ?)",
            (row["slug"], model_name, blob, time.time()),
        )
        if (i + 1) % 20 == 0:
            conn.commit()
            print(f"  {i+1}/{len(to_embed)}", file=sys.stderr, flush=True)

    conn.commit()
    print(f"  Done. {len(to_embed)} atoms embedded.", file=sys.stderr, flush=True)
