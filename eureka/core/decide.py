"""Decide — decision support pipeline backed by the knowledge graph."""

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from eureka.core.ask import ask
from eureka.core.activity import log_activity
from eureka.core.db import atom_table, atom_title_expr, transaction


def _read_atom_bodies(conn: sqlite3.Connection, slugs: list[str], limit: int = 10) -> list[dict]:
    """Fetch title + body for a list of atom slugs (up to limit)."""
    tbl = atom_table(conn)
    title_expr = atom_title_expr(conn)
    results = []
    for slug in slugs[:limit]:
        row = conn.execute(
            f"SELECT slug, {title_expr} AS title, body FROM {tbl} WHERE slug = ?",
            (slug,),
        ).fetchone()
        if row and row["body"]:
            results.append({"slug": row["slug"], "title": row["title"], "body": row["body"]})
    return results


def _build_prompt(question: str, atoms: list[dict], profile: list[dict],
                  tensions: list[dict], context: str | None) -> str:
    """Build the LLM prompt for decision analysis."""
    parts = [
        "You are a decision analyst. Analyze the following decision using the provided knowledge base.",
        "",
        f"## Decision Question\n{question}",
    ]

    if context:
        parts.append(f"\n## Additional Context\n{context}")

    if atoms:
        parts.append("\n## Relevant Knowledge")
        for a in atoms:
            parts.append(f"\n### {a['title']}\n{a['body'][:500]}")

    if profile:
        parts.append("\n## User Goals & Values")
        for p in profile:
            parts.append(f"- {p['key']}: {p['value']}")

    if tensions:
        parts.append("\n## Detected Tensions")
        for t in tensions:
            parts.append(f"- {t['a']} <-> {t['b']} (bridge: {t['bridge']}, score: {t['tension_score']})")

    parts.append("""
## Instructions
Analyze this decision thoroughly. Consider the knowledge, goals, and tensions above.
Respond with ONLY a JSON object (no markdown fencing, no extra text) with these keys:
- "for_arguments": list of strings — arguments in favor
- "against_arguments": list of strings — arguments against
- "tensions": list of strings — key tensions or tradeoffs
- "unknowns": list of strings — things that would change the answer if known
- "recommendation": string — your recommendation with reasoning""")

    return "\n".join(parts)


def _parse_json_response(text: str) -> dict | None:
    """Parse JSON from LLM response, handling markdown code blocks."""
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _slugify(text: str) -> str:
    """Turn a question into a filesystem-safe slug."""
    slug = text.lower().strip().rstrip("?").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")[:80]
    return f"decision-{slug}"


def _write_molecule(
    brain_dir: Path,
    conn: sqlite3.Connection,
    question: str,
    result: dict,
    atom_slugs: list[str],
) -> str:
    """Write a decision molecule markdown file and insert into DB. Returns slug."""
    slug = _slugify(question)
    today = date.today().isoformat()

    # Build markdown
    atoms_yaml = "\n".join(f"  - {s}" for s in atom_slugs)
    sections = [
        f"---\ntype: molecule\ntags: [decision]\ndate: {today}\natoms:\n{atoms_yaml}\n---",
        f"\n# Decision: {question}",
    ]

    if result.get("for_arguments"):
        sections.append("\n## For")
        for arg in result["for_arguments"]:
            sections.append(f"- {arg}")

    if result.get("against_arguments"):
        sections.append("\n## Against")
        for arg in result["against_arguments"]:
            sections.append(f"- {arg}")

    if result.get("tensions"):
        sections.append("\n## Tensions")
        for t in result["tensions"]:
            sections.append(f"- {t}")

    if result.get("unknowns"):
        sections.append("\n## Unknowns")
        for u in result["unknowns"]:
            sections.append(f"- {u}")

    if result.get("recommendation"):
        sections.append(f"\n## Recommendation\n{result['recommendation']}")

    md = "\n".join(sections) + "\n"

    # Write file
    mol_dir = brain_dir / "molecules"
    mol_dir.mkdir(exist_ok=True)
    (mol_dir / f"{slug}.md").write_text(md)

    # Insert into molecules table
    with transaction(conn):
        conn.execute(
            "INSERT OR REPLACE INTO molecules (slug, title, method, score, status, eli5, body) "
            "VALUES (?, ?, 'decision', 0, 'accepted', ?, ?)",
            (slug, f"Decision: {question}", result.get("recommendation", "")[:200], md),
        )
        for atom_slug in atom_slugs:
            conn.execute(
                "INSERT OR IGNORE INTO molecule_atoms (molecule_slug, atom_slug) VALUES (?, ?)",
                (slug, atom_slug),
            )

    return slug


def _ensure_decisions_table(conn: sqlite3.Connection) -> None:
    """Create decisions table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            result_json TEXT,
            molecule_slug TEXT,
            outcome TEXT,
            resolved_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def decide(
    question: str,
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
    llm,
    *,
    context: str | None = None,
    file_back: bool = True,
    brain_dir: Path | None = None,
) -> dict:
    """Run the decision support pipeline.

    1. Retrieve relevant atoms, tensions, profile via ask()
    2. Read atom bodies from DB
    3. Build prompt and call LLM
    4. Parse structured response
    5. Optionally file as molecule + decisions row
    6. Log activity

    Returns dict with question, for_arguments, against_arguments, tensions,
    unknowns, recommendation, and molecule_slug (if filed).
    """
    # 1. Graph-aware retrieval
    retrieval = ask(question, conn, embeddings)

    # 2. Collect slugs and read atom bodies
    nearest_slugs = [item["slug"] for item in retrieval["nearest"]]
    tension_slugs = []
    for t in retrieval["tensions"]:
        for key in ("a", "b", "bridge"):
            if t[key] not in nearest_slugs and t[key] not in tension_slugs:
                tension_slugs.append(t[key])

    all_slugs = nearest_slugs + tension_slugs
    atoms = _read_atom_bodies(conn, all_slugs, limit=10)

    # 3. Build prompt
    prompt = _build_prompt(
        question,
        atoms,
        retrieval["profile_context"],
        retrieval["tensions"],
        context,
    )

    # 4. Call LLM and parse
    raw = llm.generate(prompt)
    parsed = _parse_json_response(raw)

    if parsed is None:
        # Fallback: return raw text as recommendation
        parsed = {
            "for_arguments": [],
            "against_arguments": [],
            "tensions": [],
            "unknowns": ["LLM returned unstructured response"],
            "recommendation": raw,
        }

    # Normalize keys
    result = {
        "for_arguments": parsed.get("for_arguments", []),
        "against_arguments": parsed.get("against_arguments", []),
        "tensions": parsed.get("tensions", []),
        "unknowns": parsed.get("unknowns", []),
        "recommendation": parsed.get("recommendation", ""),
    }

    # 5. File as molecule + decision row
    molecule_slug = None
    atom_slugs_used = [a["slug"] for a in atoms]

    if file_back and brain_dir is not None:
        molecule_slug = _write_molecule(brain_dir, conn, question, result, atom_slugs_used)

        _ensure_decisions_table(conn)
        with transaction(conn):
            conn.execute(
                "INSERT INTO decisions (question, result_json, molecule_slug) VALUES (?, ?, ?)",
                (question, json.dumps(result), molecule_slug),
            )

    # 6. Log activity
    log_activity(conn, "decide", slug=molecule_slug, query=question)

    return {
        "question": question,
        "for_arguments": result["for_arguments"],
        "against_arguments": result["against_arguments"],
        "tensions": result["tensions"],
        "unknowns": result["unknowns"],
        "recommendation": result["recommendation"],
        "molecule_slug": molecule_slug,
        "atoms_consulted": atom_slugs_used,
    }
