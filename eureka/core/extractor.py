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


YOUTUBE_EXTRACTION_PROMPT = """Extract atomic concepts from this YouTube video transcript.

For each concept, output EXACTLY this format:

# Title — a short opinionated assertion (not a description)

Body paragraph explaining the concept. Link related ideas using [[kebab-case-slug]] wikilinks inline — e.g. this connects to [[mimetic-desire]] and [[skin-in-the-game]]. Every atom MUST have at least one [[wikilink]].

tags: tag1, tag2, tag3

Rules:
- Separate each atom with --- on its own line
- Title must be an opinionated claim, not a topic label (YES: "Agents make coding a supervision problem" / NO: "AI agents")
- Body must include at least one [[wikilink]] to a related concept
- The tags: line is REQUIRED — pick 2-4 from existing tags below, or invent specific ones
- Do NOT output numbering, bullets, or any other formatting — just the H1, body paragraph, and tags line

Existing tags to reuse when they fit: {existing_tags}

Example atom:

# Token throughput replaces GPU utilization as the developer bottleneck

The psychological shift mirrors what PhD students felt about maxing out [[gpu-compute]]: now it's about maximizing token spend. If you have unused API quota at end of day, you wasted capacity. This reframes [[developer-productivity]] from keystrokes-per-hour to instructions-per-hour.

tags: ai, agents, developer-productivity

---

Video: {video_title}
Channel: {channel}

Transcript:
{chunk_text}"""


def extract_atoms(chunks: list[str], existing_tags: list[str], llm,
                  source_type: str = "book",
                  source_metadata: dict | None = None) -> list[dict]:
    """Build extraction prompt, call LLM, return parsed atoms.

    Args:
        source_type: "paper" uses claim-focused prompt, anything else uses default.

    Raises:
        RuntimeError: If the LLM call fails after retries.
    """
    chunk_text = "\n\n---\n\n".join(chunks)
    tags_str = ", ".join(existing_tags)
    source_metadata = source_metadata or {}

    if source_type == "paper":
        prompt = PAPER_EXTRACTION_PROMPT.format(existing_tags=tags_str, chunk_text=chunk_text)
    elif source_type == "youtube":
        prompt = YOUTUBE_EXTRACTION_PROMPT.format(
            existing_tags=tags_str,
            chunk_text=chunk_text,
            video_title=source_metadata.get("title", "Unknown"),
            channel=source_metadata.get("channel", "Unknown"),
        )
    else:
        prompt = DEFAULT_EXTRACTION_PROMPT.format(existing_tags=tags_str, chunk_text=chunk_text)

    try:
        response = llm.generate(prompt)
    except Exception as e:
        raise RuntimeError(f"LLM extraction failed: {e}") from e
    return parse_extraction_response(response)
