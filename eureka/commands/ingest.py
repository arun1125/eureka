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
    try:
        from eureka.core.llm import get_llm as _get_llm, GeminiCLI, load_llm_config
        import shutil
        llm = _get_llm(config=load_llm_config(brain_dir))
        if isinstance(llm, GeminiCLI) and shutil.which("gemini") is None:
            print("Warning: gemini CLI not found on PATH. LLM disabled.", file=sys.stderr)
            return None
        return llm
    except Exception:
        return None


def run_ingest(source: str, brain_dir_path: str) -> None:
    brain_dir = Path(brain_dir_path)

    # Validate source exists (for file paths, not URLs)
    is_url = source.startswith(("http://", "https://"))
    is_arxiv = source.startswith("arxiv:")
    if not is_url and not is_arxiv and not Path(source).exists():
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
    atom_slugs = []
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
            atom_slugs.append(slug)

    # Re-index, embed, and link if atoms were created
    if atoms_created > 0:
        conn = open_db(brain_dir / "brain.db")
        try:
            from eureka.core.index import rebuild_index
            from eureka.core.embeddings import ensure_embeddings
            from eureka.core.linker import link_all
            print(f"Indexing {atoms_created} atoms...", file=sys.stderr, flush=True)
            rebuild_index(conn, brain_dir)
            print("Embedding...", file=sys.stderr, flush=True)
            ensure_embeddings(conn, brain_dir)
            print("Linking...", file=sys.stderr, flush=True)
            link_all(conn)
            print("Done.", file=sys.stderr, flush=True)
        finally:
            conn.close()

    # Paper-specific: create reference stubs and citation edges
    stubs_info = {}
    if source_type == "paper" and result.get("references"):
        conn = open_db(brain_dir / "brain.db")
        try:
            from eureka.core.citation_graph import build_reference_stubs
            print(f"Building citation graph ({len(result['references'])} references)...",
                  file=sys.stderr, flush=True)
            stubs_info = build_reference_stubs(conn, result["references"], atom_slugs)
            print(f"Created {stubs_info['stubs_created']} stubs, "
                  f"{stubs_info['edges_created']} citation edges.", file=sys.stderr, flush=True)
        finally:
            conn.close()

    emit(envelope(True, "ingest", {
        "source": {
            "id": source_id,
            "title": title,
            "type": source_type,
            "url": source,
            "chunk_count": len(chunks),
        },
        "atoms_created": atoms_created,
        **stubs_info,
    }))
