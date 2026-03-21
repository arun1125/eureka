"""Profile — onboarding interview, extract user identity, retrieve by relevance."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from eureka.core.extractor import parse_extraction_response
from eureka.core.index import rebuild_index
from eureka.core.activity import log_activity
from eureka.core.embeddings import cosine_sim


def get_questions() -> list[str]:
    """Return onboarding interview questions."""
    return [
        "What are you working on right now?",
        "What are your goals for the next 6-12 months?",
        "What do you struggle with most?",
        "What kind of person do you want to become?",
        "What topics interest you most?",
    ]


def _build_profile_prompt(answers_text: str) -> str:
    """Build an extraction prompt tuned for profile/identity extraction."""
    return f"""You are helping someone articulate who they are.
Extract their goals, patterns, values, and struggles as atomic concepts.
Each concept should be a single independent insight — personal and honest.

For each concept, output:
- A title as an H1 heading (# Title) — write it as a claim, not a topic
- A body paragraph explaining the idea in the person's own voice
- A tags line starting with "profile" plus other relevant tags

Separate each atom with --- on its own line.

Answers:
{answers_text}"""


def process_answers(
    conn: sqlite3.Connection,
    brain_dir: Path,
    answers_text: str,
    llm,
) -> dict:
    """Extract profile atoms from onboarding answers.

    Returns dict with extracted atoms info.
    """
    prompt = _build_profile_prompt(answers_text)
    response = llm.generate(prompt)
    atoms = parse_extraction_response(response)

    # Write atom .md files
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir(exist_ok=True)
    for atom in atoms:
        md = f"# {atom['title']}\n\n{atom['body']}\n\ntags: {', '.join(atom['tags'])}\n"
        (atoms_dir / f"{atom['slug']}.md").write_text(md)

    # Re-index to pick up new atoms
    rebuild_index(conn, brain_dir)

    # Insert profile rows
    for atom in atoms:
        conn.execute(
            """INSERT OR REPLACE INTO profile (key, value, source, confidence, created_at, updated_at)
               VALUES (?, ?, 'onboarding', 1.0, datetime('now'), datetime('now'))""",
            (atom["slug"], atom["title"]),
        )

    # Create source row
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO sources (title, type, ingested_at, atom_count, raw_text) VALUES (?, ?, ?, ?, ?)",
        (f"profile-{now[:10]}", "profile", now, len(atoms), answers_text),
    )
    conn.commit()

    # Log activity
    log_activity(conn, "profile")

    return {
        "atoms_extracted": atoms,
    }


def get_profile(conn: sqlite3.Connection) -> list[dict]:
    """Return all profile entries as list of dicts."""
    rows = conn.execute("SELECT key, value, source, confidence FROM profile").fetchall()
    return [dict(r) for r in rows]


def get_relevant_profile(
    conn: sqlite3.Connection,
    embeddings: dict[str, list[float]],
    query_embedding: list[float],
    threshold: float = 0.3,
) -> list[dict]:
    """Return profile entries whose atom embedding is similar to the query."""
    profile_rows = conn.execute("SELECT key, value, source, confidence FROM profile").fetchall()
    results = []
    for row in profile_rows:
        slug = row["key"]
        if slug not in embeddings:
            continue
        sim = cosine_sim(embeddings[slug], query_embedding)
        if sim >= threshold:
            entry = dict(row)
            entry["similarity"] = round(sim, 4)
            results.append(entry)
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results
