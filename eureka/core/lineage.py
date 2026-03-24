"""Lineage — trace the full provenance chain for any atom or molecule."""

import sqlite3
import sys

from eureka.core.db import atom_table


def trace_lineage(conn: sqlite3.Connection, slug: str) -> dict | None:
    """Trace full lineage for a slug. Returns dict for JSON envelope, or None if not found."""
    _atbl = atom_table(conn)

    # Check if it's an atom
    atom = conn.execute(
        f"SELECT slug, title, body, source_id, created_at FROM {_atbl} WHERE slug = ?",
        (slug,)
    ).fetchone()

    if atom:
        return _trace_atom(conn, atom, _atbl)

    # Check if it's a molecule
    molecule = conn.execute(
        "SELECT slug, title, method, score, candidate_score, llm_model, "
        "review_status, discovery_run_id, created_at FROM molecules WHERE slug = ?",
        (slug,)
    ).fetchone()

    if molecule:
        return _trace_molecule(conn, molecule, _atbl)

    return None


def _trace_atom(conn: sqlite3.Connection, atom, _atbl: str) -> dict:
    slug = atom["slug"]

    # Source info
    source_info = None
    if atom["source_id"]:
        src = conn.execute(
            "SELECT id, title, type, url, ingested_at FROM sources WHERE id = ?",
            (atom["source_id"],)
        ).fetchone()
        if src:
            source_info = {
                "id": src["id"],
                "title": src["title"],
                "type": src["type"],
                "url": src["url"],
                "ingested_at": src["ingested_at"],
            }

    # Molecules this atom appears in
    molecules = []
    rows = conn.execute(
        "SELECT ma.molecule_slug, ma.role, m.title, m.method, m.score, m.review_status "
        "FROM molecule_atoms ma JOIN molecules m ON ma.molecule_slug = m.slug "
        "WHERE ma.atom_slug = ? ORDER BY m.score DESC",
        (slug,)
    ).fetchall()
    for r in rows:
        molecules.append({
            "slug": r["molecule_slug"],
            "title": r["title"],
            "method": r["method"],
            "score": r["score"],
            "review_status": r["review_status"],
            "role": r["role"],
        })

    # Top edges
    edges = []
    rows = conn.execute(
        "SELECT target, similarity FROM edges WHERE source = ? ORDER BY similarity DESC LIMIT 5",
        (slug,)
    ).fetchall()
    for r in rows:
        edges.append({"target": r["target"], "similarity": r["similarity"]})

    result = {
        "type": "atom",
        "slug": slug,
        "title": atom["title"],
        "created_at": atom["created_at"],
        "source": source_info,
        "molecules": molecules,
        "top_edges": edges,
    }

    # Print human-readable to stderr
    _print_atom_lineage(result)
    return result


def _trace_molecule(conn: sqlite3.Connection, molecule, _atbl: str) -> dict:
    slug = molecule["slug"]

    # Discovery run info
    run_info = None
    if molecule["discovery_run_id"]:
        run = conn.execute(
            "SELECT id, method, timestamp, candidates_found, candidates_accepted "
            "FROM discovery_runs WHERE id = ?",
            (molecule["discovery_run_id"],)
        ).fetchone()
        if run:
            run_info = {
                "id": run["id"],
                "method": run["method"],
                "timestamp": run["timestamp"],
                "candidates_found": run["candidates_found"],
                "candidates_accepted": run["candidates_accepted"],
            }

    # Constituent atoms with their sources
    atoms = []
    rows = conn.execute(
        f"SELECT ma.atom_slug, ma.role, a.title, a.source_id "
        f"FROM molecule_atoms ma LEFT JOIN {_atbl} a ON ma.atom_slug = a.slug "
        f"WHERE ma.molecule_slug = ?",
        (slug,)
    ).fetchall()
    for r in rows:
        atom_info = {
            "slug": r["atom_slug"],
            "title": r["title"],
            "role": r["role"],
            "source": None,
        }
        if r["source_id"]:
            src = conn.execute(
                "SELECT title, type FROM sources WHERE id = ?",
                (r["source_id"],)
            ).fetchone()
            if src:
                atom_info["source"] = {"title": src["title"], "type": src["type"]}
        atoms.append(atom_info)

    result = {
        "type": "molecule",
        "slug": slug,
        "title": molecule["title"],
        "method": molecule["method"],
        "score": molecule["score"],
        "candidate_score": molecule["candidate_score"],
        "llm_model": molecule["llm_model"],
        "review_status": molecule["review_status"],
        "created_at": molecule["created_at"],
        "discovery_run": run_info,
        "atoms": atoms,
    }

    _print_molecule_lineage(result)
    return result


def _print_atom_lineage(data: dict) -> None:
    """Print human-readable atom lineage to stderr."""
    src = data["source"]
    if src:
        print(f'Source: "{src["title"]}" ({src["type"]}, ingested {src["ingested_at"]})',
              file=sys.stderr)
    else:
        print("Source: unknown", file=sys.stderr)

    print(f'  └─ Atom: "{data["slug"]}"', file=sys.stderr)

    for mol in data["molecules"]:
        role_tag = f" [{mol['role']}]" if mol["role"] != "member" else ""
        status = mol["review_status"] or "pending"
        print(f'       ├─ Molecule: "{mol["slug"]}"{role_tag} '
              f'({mol["method"]}, score {mol["score"]:.0f}, {status})',
              file=sys.stderr)

    if data["top_edges"]:
        top = data["top_edges"][0]
        print(f'       └─ {len(data["top_edges"])} edges '
              f'(top: {top["target"]} {top["similarity"]:.2f})',
              file=sys.stderr)


def _print_molecule_lineage(data: dict) -> None:
    """Print human-readable molecule lineage to stderr."""
    print(f'Molecule: "{data["slug"]}"', file=sys.stderr)

    run = data["discovery_run"]
    if run:
        cand = f'Candidate: {data["candidate_score"]:.1f}' if data["candidate_score"] else ""
        print(f'  ├─ Method: {data["method"]} | Run #{run["id"]} ({run["timestamp"]}) '
              f'| {cand} → Final: {data["score"]:.1f}', file=sys.stderr)
    else:
        print(f'  ├─ Method: {data["method"]} | Score: {data["score"]:.1f}', file=sys.stderr)

    llm = data["llm_model"] or "unknown"
    print(f'  ├─ LLM: {llm} | Status: {data["review_status"]}', file=sys.stderr)

    print("  └─ Atoms:", file=sys.stderr)
    for i, atom in enumerate(data["atoms"]):
        role_tag = f" [{atom['role']}]" if atom["role"] and atom["role"] != "member" else ""
        src = f' ← "{atom["source"]["title"]}"' if atom.get("source") else ""
        prefix = "       ├─" if i < len(data["atoms"]) - 1 else "       └─"
        title = atom["title"] or atom["slug"]
        print(f'{prefix} {title}{role_tag}{src}', file=sys.stderr)
