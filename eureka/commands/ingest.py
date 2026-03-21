"""eureka ingest — read a source and store it in the DB."""

import sys
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.extractor import extract_atoms
from eureka.core.output import emit, envelope
from eureka.readers.base import detect_reader


def get_llm(brain_dir: Path):
    """Return an LLM instance for extraction. Monkeypatch this in tests."""
    return None


def run_ingest(source: str, brain_dir_path: str) -> None:
    brain_dir = Path(brain_dir_path)

    # Validate source exists (for file paths, not URLs)
    is_url = source.startswith(("http://", "https://"))
    if not is_url and not Path(source).exists():
        emit(envelope(False, "ingest", {"message": f"Source not found: {source}"}))
        sys.exit(3)

    # Read source
    reader = detect_reader(source)
    result = reader.read(source)
    title = result["title"]
    source_type = result["type"]
    chunks = result["chunks"]
    raw_text = "\n\n".join(chunks)

    # Open DB
    conn = open_db(brain_dir / "brain.db")

    # Check idempotency — same url means already ingested
    existing = conn.execute("SELECT id, title, type, url, chunk_count FROM sources WHERE url = ?", (source,)).fetchone()
    if existing:
        emit(envelope(True, "ingest", {
            "already_ingested": True,
            "source": {
                "id": existing["id"],
                "title": existing["title"],
                "type": existing["type"],
                "url": existing["url"],
                "chunk_count": existing["chunk_count"],
            },
        }))
        conn.close()
        return

    # Insert source row
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO sources (title, type, url, ingested_at, chunk_count, raw_text) VALUES (?, ?, ?, ?, ?, ?)",
        (title, source_type, source, now, len(chunks), raw_text),
    )
    conn.commit()
    source_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    # Extract atoms via LLM (if available)
    atoms_created = 0
    llm = get_llm(brain_dir)
    if llm is not None:
        # Gather existing tags from current atoms
        atoms_dir = brain_dir / "atoms"
        existing_tags: list[str] = []
        if atoms_dir.exists():
            for md in atoms_dir.glob("*.md"):
                for line in md.read_text().split("\n"):
                    if line.strip().startswith("tags:"):
                        raw = line.split(":", 1)[1].strip()
                        existing_tags.extend(t.strip() for t in raw.split(",") if t.strip())
            existing_tags = sorted(set(existing_tags))

        atoms = extract_atoms(chunks, existing_tags, llm)

        # Write each atom as .md
        atoms_dir.mkdir(parents=True, exist_ok=True)
        for atom in atoms:
            slug = atom["slug"]
            md_path = atoms_dir / f"{slug}.md"
            body_with_links = atom["body"]
            tags_line = f"tags: {', '.join(atom['tags'])}" if atom["tags"] else "tags:"
            content = f"# {atom['title']}\n\n{body_with_links}\n\n{tags_line}\n"
            md_path.write_text(content)
            atoms_created += 1

    emit(envelope(True, "ingest", {
        "source": {
            "id": source_id,
            "title": title,
            "type": source_type,
            "url": source,
            "chunk_count": len(chunks),
        },
        "atoms_created": atoms_created,
    }))
