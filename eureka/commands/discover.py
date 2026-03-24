"""eureka discover — find molecule candidates and write top one."""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.discovery import discover_all
from eureka.core.embeddings import _unpack_vector
from eureka.core.output import emit, envelope


def get_llm(brain_dir):
    """Return an LLM instance for molecule writing. Monkeypatch in tests."""
    try:
        from eureka.core.llm import get_llm as _get_llm, load_llm_config
        llm = _get_llm(config=load_llm_config(brain_dir))
        return llm
    except RuntimeError as e:
        print(f"LLM error: {e}", file=sys.stderr, flush=True)
        return None


def _load_embeddings(conn):
    """Load all embeddings from DB, unpacking BLOBs to lists."""
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    return {r["slug"]: _unpack_vector(r["vector"]) for r in rows}


def _slugify(title: str) -> str:
    """Convert a title to a slug."""
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s]+", "-", s)
    return s[:80].strip("-")


def run_discover(brain_dir_path: str, method: str = "all", count: int = 10) -> None:
    brain_dir = Path(brain_dir_path)
    conn = open_db(brain_dir)
    now = datetime.now(timezone.utc).isoformat()

    # Load embeddings
    embeddings = _load_embeddings(conn)

    # Run discovery — skip candidates that already exist as molecules
    try:
        all_candidates = discover_all(conn, embeddings, method=method)
    except ValueError as e:
        conn.close()
        emit(envelope(False, "discover", {"message": str(e)}))
        import sys as _sys
        _sys.exit(2)
        return
    existing_slugs = {r["slug"] for r in conn.execute("SELECT slug FROM molecules").fetchall()}
    candidates = []
    for c in all_candidates:
        slug = _slugify(c["atoms"][0] + "-" + c["atoms"][1]) if len(c["atoms"]) >= 2 else ""
        if slug not in existing_slugs:
            candidates.append(c)
        if len(candidates) >= count:
            break

    # Log discovery run and capture run_id
    conn.execute(
        "INSERT INTO discovery_runs (method, timestamp, candidates_found) VALUES (?, ?, ?)",
        (method, now, len(candidates)),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    # If LLM available and candidates found, write molecules
    llm = get_llm(brain_dir)
    molecules_written = 0
    llm_model_name = None
    if llm is not None:
        raw_model = getattr(llm, "model", None)
        llm_model_name = str(raw_model) if raw_model else None

    if llm is not None and candidates:
        mol_dir = brain_dir / "molecules"
        mol_dir.mkdir(parents=True, exist_ok=True)

        for candidate in candidates:
            atom_slugs = candidate["atoms"]
            score = candidate.get("score", 0)
            method_name = candidate.get("method", "unknown")

            # Build prompt for molecule writing
            from eureka.core.db import atom_table, atom_title_expr
            _atbl = atom_table(conn)
            _title_expr = atom_title_expr(conn)
            atom_bodies = {}
            for slug in atom_slugs:
                row = conn.execute(f"SELECT {_title_expr} AS title, body FROM {_atbl} WHERE slug = ?", (slug,)).fetchone()
                if row:
                    atom_bodies[slug] = f"# {row['title']}\n\n{row['body']}"

            prompt = (
                "Write a molecule — a synthesis note that connects these atoms into a single insight none of them state alone.\n\n"
                "Here are the atoms:\n\n"
                + "\n\n---\n\n".join(f"[[{s}]]\n{atom_bodies.get(s, '')}" for s in atom_slugs)
                + "\n\n---\n\n"
                "Write the molecule in EXACTLY this format (no deviations):\n\n"
                "```\n"
                "# Title as a short opinionated claim (under 80 chars)\n"
                "\n"
                "First paragraph: weave the atoms together, explaining WHY these ideas connect — not just THAT they connect. "
                "Use [[wikilinks]] to reference atoms naturally in the flow. Write like an essay, not a list.\n"
                "\n"
                "Second paragraph: extract the higher-order principle — the thing you can only see once all atoms are in view. "
                "This is the payoff. Be specific and actionable.\n"
                "\n"
                "eli5: One vivid sentence a 10-year-old would understand. Use a concrete metaphor or image, not abstract language.\n"
                "```\n\n"
                "Rules:\n"
                "- Title must be a SHORT claim (under 80 chars). No wikilinks in the title.\n"
                "- Body should be 2 paragraphs, 4-8 sentences total.\n"
                "- ELI5 must use a physical metaphor (not 'it's like when you...' but a specific image).\n"
                "- Do NOT just summarize the atoms — synthesize them into something new.\n"
            )

            try:
                print(f"Writing molecule {molecules_written + 1}/{len(candidates)} ({method_name})...", file=sys.stderr, flush=True)
                response = llm.generate(prompt)
            except Exception as e:
                print(f"LLM error writing molecule for {atom_slugs}: {e}", file=sys.stderr, flush=True)
                continue

            # Parse response — strip code fences and extract fields
            raw = response.strip()
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
            lines = raw.strip().split("\n")
            title = ""
            eli5 = ""
            body_lines = []

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    continue  # skip any remaining fences
                if line.startswith("# ") and not title:
                    title = line[2:].strip()
                elif stripped.lower().startswith("eli5:"):
                    eli5 = line.split(":", 1)[1].strip()
                else:
                    body_lines.append(line)

            body = "\n".join(body_lines).strip()
            slug = _slugify(title) if title else f"molecule-{now}-{molecules_written}"

            # Store in DB with lineage
            import hashlib
            file_content = response.strip() + "\n"
            file_hash = hashlib.sha256(file_content.encode()).hexdigest()
            conn.execute(
                "INSERT OR REPLACE INTO molecules "
                "(slug, title, method, score, review_status, eli5, body, created_at, "
                " discovery_run_id, candidate_score, llm_model, file_hash) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)",
                (slug, title, method_name, score, eli5, body, now,
                 run_id, score, llm_model_name, file_hash),
            )
            # Determine atom roles from candidate metadata
            bridge_atom = candidate.get("bridge")
            hinge_atom = candidate.get("hinge")
            for atom_slug in atom_slugs:
                role = "member"
                if atom_slug == bridge_atom:
                    role = "bridge"
                elif atom_slug == hinge_atom:
                    role = "hinge"
                conn.execute(
                    "INSERT OR IGNORE INTO molecule_atoms (molecule_slug, atom_slug, role) VALUES (?, ?, ?)",
                    (slug, atom_slug, role),
                )
            conn.commit()

            # Write .md file
            md_path = mol_dir / f"{slug}.md"
            md_path.write_text(file_content)
            molecules_written += 1

    # Update discovery run with actual molecules written
    conn.execute(
        "UPDATE discovery_runs SET candidates_accepted = ? WHERE id = ?",
        (molecules_written, run_id),
    )

    # Log operation
    from eureka.core.db import log_operation
    log_operation(conn, "discover", detail={
        "run_id": run_id, "method": method,
        "candidates_found": len(candidates),
        "molecules_written": molecules_written,
        "llm_model": llm_model_name,
    })
    conn.commit()
    conn.close()

    emit(envelope(True, "discover", {
        "candidates_found": len(candidates),
        "molecules_written": molecules_written,
        "method": method,
        "discovery_run_id": run_id,
    }))
