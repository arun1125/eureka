"""Extract atoms from LLM output."""

import re


def _slugify(title: str) -> str:
    """Convert title to kebab-case slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def parse_extraction_response(text: str) -> list[dict]:
    """Split LLM output on --- separators and parse each atom."""
    blocks = re.split(r"\n---\n?", text.strip())
    atoms = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")

        # Title from first H1 line
        title = ""
        title_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("# "):
                title = line[2:].strip()
                title_idx = i
                break

        # Find tags line
        tags_line_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip().startswith("tags:"):
                tags_line_idx = i
                break

        # Body: between title and tags
        body_end = tags_line_idx if tags_line_idx is not None else len(lines)
        body = "\n".join(lines[title_idx + 1 : body_end]).strip()

        # Tags
        tags: list[str] = []
        if tags_line_idx is not None:
            raw = lines[tags_line_idx].split(":", 1)[1].strip()
            if raw:
                tags = [t.strip() for t in raw.split(",") if t.strip()]

        # Wikilinks
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", body)

        slug = _slugify(title)

        atoms.append({
            "title": title,
            "body": body,
            "tags": tags,
            "wikilinks": wikilinks,
            "slug": slug,
        })
    return atoms


def extract_atoms(chunks: list[str], existing_tags: list[str], llm) -> list[dict]:
    """Build extraction prompt, call LLM, return parsed atoms."""
    chunk_text = "\n\n---\n\n".join(chunks)
    prompt = f"""Extract atomic concepts from the following text. For each concept, output:
- A title as an H1 heading (# Title)
- A body paragraph explaining the concept
- Any wikilinks to related concepts as [[slug]]
- A tags line with comma-separated tags

Reuse existing tags where appropriate: {', '.join(existing_tags)}

Separate each atom with --- on its own line.

Text:
{chunk_text}"""

    response = llm.generate(prompt)
    return parse_extraction_response(response)
