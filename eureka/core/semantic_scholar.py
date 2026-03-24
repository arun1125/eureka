"""Semantic Scholar API — enrich reference stubs with abstracts and metadata."""

import json
import time
import urllib.request
import urllib.error
import sys

BASE_URL = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,abstract,year,authors,citationCount,tldr,externalIds"

# Rate limit: 100 requests per 5 minutes (free tier)
# We'll be conservative: 1 request per 3 seconds
REQUEST_DELAY = 3.0
MAX_RETRIES = 3


_rate_limit_hits = 0  # track consecutive rate limits across calls


def _fetch(url: str) -> dict | None:
    """Fetch a URL with retries and rate limit handling."""
    global _rate_limit_hits
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Eureka/0.1 (research tool)")
            resp = urllib.request.urlopen(req, timeout=30)
            _rate_limit_hits = 0  # reset on success
            return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _rate_limit_hits += 1
                if _rate_limit_hits >= 6:
                    print("  S2 rate limit exceeded repeatedly — skipping remaining enrichment.", file=sys.stderr, flush=True)
                    return None
                wait = (attempt + 1) * 10
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr, flush=True)
                time.sleep(wait)
            elif e.code == 404:
                return None
            else:
                print(f"  S2 API error {e.code}: {e.reason}", file=sys.stderr, flush=True)
                return None
        except Exception as e:
            print(f"  S2 fetch error: {e}", file=sys.stderr, flush=True)
            return None
    return None


def lookup_by_arxiv(arxiv_id: str) -> dict | None:
    """Lookup a paper by arXiv ID."""
    url = f"{BASE_URL}/paper/ArXiv:{arxiv_id}?fields={FIELDS}"
    time.sleep(REQUEST_DELAY)
    return _fetch(url)


def lookup_by_title(title: str) -> dict | None:
    """Search for a paper by title and return the best match."""
    encoded = urllib.request.quote(title)
    url = f"{BASE_URL}/paper/search?query={encoded}&fields={FIELDS}&limit=1"
    time.sleep(REQUEST_DELAY)
    data = _fetch(url)
    if data and data.get("data") and len(data["data"]) > 0:
        return data["data"][0]
    return None


def enrich_reference(ref: dict) -> dict | None:
    """Try to enrich a single reference with Semantic Scholar data.

    Tries arXiv ID first (exact match), falls back to title search.
    Returns enriched dict or None if not found.
    """
    paper = None

    # Try arXiv ID first (most reliable)
    if ref.get("arxiv_id"):
        paper = lookup_by_arxiv(ref["arxiv_id"])

    # Fall back to title search
    if paper is None and ref.get("title"):
        paper = lookup_by_title(ref["title"])

    if paper is None:
        return None

    result = {
        "title": paper.get("title", ref.get("title", "")),
        "abstract": paper.get("abstract", ""),
        "year": paper.get("year"),
        "citation_count": paper.get("citationCount", 0),
    }

    # Authors
    authors = paper.get("authors", [])
    if authors:
        result["authors"] = [a.get("name", "") for a in authors]

    # TLDR
    tldr = paper.get("tldr")
    if tldr and isinstance(tldr, dict):
        result["tldr"] = tldr.get("text", "")

    # External IDs (DOI, arXiv, etc.)
    ext = paper.get("externalIds", {})
    if ext:
        if ext.get("DOI"):
            result["doi"] = ext["DOI"]
        if ext.get("ArXiv"):
            result["arxiv_id"] = ext["ArXiv"]

    return result


def enrich_all_references(references: list[dict],
                          progress_callback=None) -> list[dict]:
    """Enrich a list of references. Returns list of enriched dicts.

    Items that couldn't be found are returned with enriched=False.
    """
    results = []
    for i, ref in enumerate(references):
        if progress_callback:
            progress_callback(i + 1, len(references), ref.get("title", "?")[:50])

        enriched = enrich_reference(ref)
        if enriched:
            enriched["enriched"] = True
            enriched["original_number"] = ref.get("number")
            results.append(enriched)
        else:
            results.append({
                "enriched": False,
                "title": ref.get("title", ""),
                "original_number": ref.get("number"),
            })

    return results
