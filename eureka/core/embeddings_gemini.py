"""Gemini Embedding API — #1 on MTEB leaderboard, 768 dims."""

import json
import os
import time
import urllib.request
import urllib.error
import sys

MODEL = "gemini-embedding-001"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:embedContent"
DELAY = 0.1  # 1500 RPM free tier = ~25/sec, we'll be conservative


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        # Try loading from .env
        env_path = os.path.expanduser("~/Desktop/00_Organized/Agents/tech/secrets/.env")
        if os.path.exists(env_path):
            for line in open(env_path):
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise RuntimeError("GEMINI_API_KEY not found")
    return key


def embed_text(text: str) -> list[float]:
    """Embed a single text via Gemini API. Returns list of floats."""
    api_key = _get_api_key()
    url = API_URL.format(MODEL) + f"?key={api_key}"

    body = json.dumps({
        "model": f"models/{MODEL}",
        "content": {"parts": [{"text": text}]},
        "taskType": "SEMANTIC_SIMILARITY",
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode())
            time.sleep(DELAY)
            return data["embedding"]["values"]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 5
                print(f"  Gemini rate limited, waiting {wait}s...", file=sys.stderr, flush=True)
                time.sleep(wait)
            else:
                err_body = e.read().decode() if hasattr(e, 'read') else str(e)
                raise RuntimeError(f"Gemini API error {e.code}: {err_body[:200]}")
    raise RuntimeError("Gemini API: max retries exceeded")


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts. Gemini doesn't have a batch endpoint, so we loop."""
    results = []
    for i, text in enumerate(texts):
        results.append(embed_text(text))
        if (i + 1) % 10 == 0:
            print(f"  Embedded {i+1}/{len(texts)}", file=sys.stderr, flush=True)
    return results
