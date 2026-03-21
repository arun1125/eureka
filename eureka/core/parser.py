"""Parse .md note files into structured dicts."""

import hashlib
import re
from pathlib import Path


def parse_note(path: Path) -> dict:
    """Parse a markdown note and return structured fields.

    Returns dict with: slug, title, body, body_hash, wikilinks, tags.
    """
    text = path.read_text()
    lines = text.split("\n")

    slug = path.stem

    # Title from H1 heading on line 1
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("# ") else ""

    # Find tags line (last non-empty line starting with "tags:")
    tags_line_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("tags:"):
            tags_line_idx = i
            break

    # Body: everything between title line and tags line, stripped
    body_start = 1  # skip title line
    body_end = tags_line_idx if tags_line_idx is not None else len(lines)
    body = "\n".join(lines[body_start:body_end]).strip()

    body_hash = hashlib.sha256(body.encode()).hexdigest()

    # Wikilinks from body
    wikilinks = re.findall(r"\[\[([^\]]+)\]\]", body)

    # Tags
    tags: list[str] = []
    if tags_line_idx is not None:
        raw = lines[tags_line_idx].split(":", 1)[1].strip()
        if raw:
            tags = [t.strip() for t in raw.split(",") if t.strip()]

    return {
        "slug": slug,
        "title": title,
        "body": body,
        "body_hash": body_hash,
        "wikilinks": wikilinks,
        "tags": tags,
    }
