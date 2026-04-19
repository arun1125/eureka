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
        from eureka.core.llm import get_llm as _get_llm, load_llm_config
        llm = _get_llm(config=load_llm_config(brain_dir))
        return llm
    except RuntimeError as e:
        print(f"LLM error: {e}", file=sys.stderr, flush=True)
        return None


def _generate_title(raw_text: str, llm) -> str:
    """Ask the LLM to name a source from its content."""
    preview = raw_text[:2000]
    prompt = (
        "Give this source a short, descriptive title (under 60 chars). "
        "Just the title, nothing else. No quotes.\n\n"
        f"{preview}"
    )
    try:
        title = llm.generate(prompt).strip().strip('"').strip("'")
        # Sanity check — if LLM returned garbage, fall back
        if len(title) > 80 or "\n" in title:
            return None
        return title
    except Exception as e:
        print(f"Title generation failed (non-fatal): {e}", file=sys.stderr, flush=True)
        return None


def run_ingest(source: str, brain_dir_path: str, deep: bool = False,
               title_override: str = None) -> None:
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
    title = title_override or result["title"]
    source_type = result["type"]
    chunks = result["chunks"]
    raw_text = "\n\n".join(chunks)
    source_metadata = result.get("metadata", {})

    # If title is just a filename and no override, try LLM naming
    if not title_override and title == Path(source).stem and not is_url and not is_arxiv:
        llm = get_llm(Path(brain_dir_path))
        if llm is not None:
            smart_title = _generate_title(raw_text, llm)
            if smart_title:
                title = smart_title
                print(f"Source titled: {title}", file=sys.stderr, flush=True)

    # Store relative path for local files, original string for URLs/arxiv
    if not is_url and not is_arxiv:
        source_url = Path(source).name
    else:
        source_url = source

    # Open DB
    conn = open_db(brain_dir / "brain.db")

    # Check idempotency — same url means already ingested
    existing = conn.execute("SELECT id, title, type, url, chunk_count FROM sources WHERE url = ?", (source_url,)).fetchone()
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
        (title, source_type, source_url, now, len(chunks), raw_text),
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

        try:
            atoms = extract_atoms(chunks, existing_tags, llm, source_type=source_type,
                                  source_metadata={"title": title, **source_metadata})
        except RuntimeError as e:
            # LLM failed — delete the source row so re-ingest is possible
            conn = open_db(brain_dir / "brain.db")
            try:
                conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
                conn.commit()
            finally:
                conn.close()
            emit(envelope(False, "ingest", {"message": f"Extraction failed: {e}"}))
            sys.exit(4)

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
            from eureka.core.db import log_operation
            print(f"Indexing {atoms_created} atoms...", file=sys.stderr, flush=True)
            rebuild_index(conn, brain_dir)

            # Wire source_id to the atoms we just created
            for slug in atom_slugs:
                conn.execute(
                    "UPDATE atoms SET source_id = ? WHERE slug = ? AND source_id IS NULL",
                    (source_id, slug),
                )
            # Update source atom count
            conn.execute(
                "UPDATE sources SET atom_count = ? WHERE id = ?",
                (atoms_created, source_id),
            )
            conn.commit()

            print("Embedding...", file=sys.stderr, flush=True)
            ensure_embeddings(conn, brain_dir)
            print("Linking...", file=sys.stderr, flush=True)
            link_all(conn)

            log_operation(conn, "ingest", detail={
                "source_id": source_id, "source": source,
                "atoms_created": atoms_created,
            })
            conn.commit()
            print("Done.", file=sys.stderr, flush=True)
        finally:
            conn.close()

    # Paper-specific: create reference stubs, citation edges, and optional enrichment
    stubs_info = {}
    enrich_info = {}
    if source_type == "paper" and result.get("references"):
        conn = open_db(brain_dir / "brain.db")
        try:
            from eureka.core.citation_graph import build_reference_stubs, enrich_stubs
            print(f"Building citation graph ({len(result['references'])} references)...",
                  file=sys.stderr, flush=True)
            stubs_info = build_reference_stubs(conn, result["references"], atom_slugs)
            print(f"Created {stubs_info['stubs_created']} stubs, "
                  f"{stubs_info['edges_created']} citation edges.", file=sys.stderr, flush=True)

            # Enrich stubs with Semantic Scholar abstracts
            print("Enriching reference stubs via Semantic Scholar...", file=sys.stderr, flush=True)
            enrich_info = enrich_stubs(
                conn, result["references"],
                progress_callback=lambda i, n, t: print(f"  [{i}/{n}] {t}", file=sys.stderr, flush=True),
            )
            print(f"Enriched {enrich_info.get('enriched', 0)} stubs, "
                  f"{enrich_info.get('not_found', 0)} not found.", file=sys.stderr, flush=True)

            # Re-embed enriched stubs
            if enrich_info.get("enriched", 0) > 0:
                from eureka.core.embeddings import ensure_embeddings
                from eureka.core.linker import link_all
                print("Re-embedding enriched stubs...", file=sys.stderr, flush=True)
                ensure_embeddings(conn, brain_dir)
                link_all(conn)
        finally:
            conn.close()

    # Deep mode: recursively ingest referenced papers that have arXiv IDs
    deep_info = {}
    if deep and source_type == "paper" and result.get("references"):
        deep_fetched = 0
        deep_skipped = 0
        deep_failed = 0
        refs_with_arxiv = [r for r in result["references"] if r.get("arxiv_id")]
        print(f"Deep mode: {len(refs_with_arxiv)} references have arXiv IDs.", file=sys.stderr, flush=True)
        for i, ref in enumerate(refs_with_arxiv):
            arxiv_src = f"arxiv:{ref['arxiv_id']}"
            # Check if already ingested
            conn = open_db(brain_dir / "brain.db")
            existing = conn.execute("SELECT id FROM sources WHERE url = ?", (arxiv_src,)).fetchone()
            conn.close()
            if existing:
                deep_skipped += 1
                continue
            print(f"  [{i+1}/{len(refs_with_arxiv)}] Fetching {arxiv_src}...", file=sys.stderr, flush=True)
            try:
                run_ingest(arxiv_src, brain_dir_path, deep=False)  # never recurse deeper
                deep_fetched += 1
            except Exception as e:
                print(f"    Failed: {e}", file=sys.stderr, flush=True)
                deep_failed += 1
        deep_info = {"deep_fetched": deep_fetched, "deep_skipped": deep_skipped, "deep_failed": deep_failed}

    # Build output
    ingest_output = {
        "source": {
            "id": source_id,
            "title": title,
            "type": source_type,
            "url": source_url,
            "chunk_count": len(chunks),
        },
        "atoms_created": atoms_created,
        **stubs_info,
        "enrichment": enrich_info,
        **deep_info,
    }

    emit(envelope(True, "ingest", ingest_output))
