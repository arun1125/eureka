"""Embeddings — embed text, cache in DB, cosine similarity.

Default: Gemini Embedding 001 (3072-dim, #1 MTEB).
Fallback: FastEmbed bge-small-en-v1.5 (384-dim) if no Gemini API key.

Configurable via brain.json:
  {"embedding": {"backend": "gemini"}}   — force Gemini
  {"embedding": {"backend": "fastembed"}} — force local FastEmbed
  Omit or set "auto" to auto-detect.
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
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"

_backend = None  # "gemini" or "fastembed"
_fastembed_model = None


def _has_gemini_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def configure_backend(backend: str) -> None:
    """Explicitly set the embedding backend ("gemini" or "fastembed")."""
    global _backend
    if backend not in ("gemini", "fastembed"):
        raise ValueError(f"Unknown embedding backend '{backend}'. Use 'gemini' or 'fastembed'.")
    _backend = backend


def _detect_backend() -> str:
    global _backend
    if _backend is None:
        _backend = "gemini" if _has_gemini_key() else "fastembed"
    return _backend


def _load_env_from_brain_dir(brain_dir: Path) -> None:
    """Load .env from brain directory into os.environ (for GEMINI_API_KEY etc.)."""
    env_path = brain_dir / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _load_backend_from_config(brain_dir: Path) -> None:
    """Load .env and read embedding.backend from brain.json if present."""
    global _backend

    # Always load .env so GEMINI_API_KEY is available for embedding
    _load_env_from_brain_dir(brain_dir)

    if _backend is not None:
        return  # already configured
    config_path = brain_dir / "brain.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            chosen = data.get("embedding", {}).get("backend", "auto")
            if chosen and chosen != "auto":
                _backend = chosen
                return
        except (json.JSONDecodeError, AttributeError):
            pass


def _get_fastembed():
    global _fastembed_model
    if _fastembed_model is None:
        from fastembed import TextEmbedding
        _fastembed_model = TextEmbedding(FASTEMBED_MODEL)
    return _fastembed_model


def embed_text(text: str) -> list[float]:
    """Embed a single text string, return list of floats."""
    backend = _detect_backend()
    if backend == "gemini":
        from eureka.core.embeddings_gemini import embed_text as gemini_embed
        return gemini_embed(text)
    else:
        model = _get_fastembed()
        vectors = list(model.embed([text]))
        return vectors[0].tolist()


def get_model_name() -> str:
    return GEMINI_MODEL if _detect_backend() == "gemini" else FASTEMBED_MODEL


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


def ensure_embeddings(conn: sqlite3.Connection, brain_dir: Path,
                      force: bool = False) -> None:
    """Embed all atoms and cache vectors in the embeddings table.

    If force=True, re-embeds everything (use when switching models).
    Otherwise idempotent — skips atoms that already have embeddings.

    Reads embedding backend preference from brain.json if not already set.
    Uses batch embedding for Gemini when embedding 5+ atoms.
    """
    from eureka.core.db import atom_table

    # Load config-specified backend if not already set
    _load_backend_from_config(brain_dir)
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

    print(f"Embedding {len(to_embed)} atoms with {model_name}...",
          file=sys.stderr, flush=True)

    backend = _detect_backend()

    # Batch path for Gemini (5+ atoms)
    if backend == "gemini" and len(to_embed) >= 5:
        from eureka.core.embeddings_gemini import embed_batch
        texts = [row["body"] for row in to_embed]
        vectors = embed_batch(texts)
        for row, vec in zip(to_embed, vectors):
            blob = _pack_vector(vec)
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (slug, model, vector, updated) VALUES (?, ?, ?, ?)",
                (row["slug"], model_name, blob, time.time()),
            )
        conn.commit()
        print(f"  Done. {len(to_embed)} atoms embedded (batch).", file=sys.stderr, flush=True)
        return

    # Sequential path (FastEmbed or small Gemini batches)
    for i, row in enumerate(to_embed):
        vec = embed_text(row["body"])
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
