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


PAPER_EXTRACTION_PROMPT = """You are extracting atomic claims from a scientific paper. For each claim, output:
- A title as an H1 heading (# Title) — a short opinionated assertion, not a description
- A body paragraph with the specific claim, evidence, conditions, and limitations
- Wikilinks to related concepts as [[slug]]
- A tags line with comma-separated tags. ALWAYS include one of these claim types as the FIRST tag:
  - finding: empirical results ("X increases Y by Z% under condition W")
  - method: techniques or approaches ("We use T to measure M")
  - hypothesis: proposed explanations ("We hypothesize that...")
  - limitation: known constraints ("This does not account for...")
  - open-question: future work or unknowns ("Future work should explore...")

Reuse existing tags where appropriate: {existing_tags}

Rules:
- State claims as the authors would — no editorializing or hindsight
- Be precise: include numbers, conditions, and scope
- Each atom should be independently understandable
- Separate each atom with --- on its own line

Text:
{chunk_text}"""


DEFAULT_EXTRACTION_PROMPT = """Extract atomic concepts from the following text. For each concept, output:
- A title as an H1 heading (# Title)
- A body paragraph explaining the concept
- Any wikilinks to related concepts as [[slug]]
- A tags line with comma-separated tags

Reuse existing tags where appropriate: {existing_tags}

Separate each atom with --- on its own line.

Text:
{chunk_text}"""


def extract_atoms(chunks: list[str], existing_tags: list[str], llm,
                  source_type: str = "book") -> list[dict]:
    """Build extraction prompt, call LLM, return parsed atoms.

    Args:
        source_type: "paper" uses claim-focused prompt, anything else uses default.
    """
    chunk_text = "\n\n---\n\n".join(chunks)
    tags_str = ", ".join(existing_tags)

    if source_type == "paper":
        prompt = PAPER_EXTRACTION_PROMPT.format(existing_tags=tags_str, chunk_text=chunk_text)
    else:
        prompt = DEFAULT_EXTRACTION_PROMPT.format(existing_tags=tags_str, chunk_text=chunk_text)

    response = llm.generate(prompt)
    return parse_extraction_response(response)
