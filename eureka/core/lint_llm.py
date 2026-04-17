"""Lint v2 — LLM-judged brain health checks.

Pre-filters atom pairs by cosine similarity, then uses an LLM to judge:
1. Contradictions: atoms that disagree with each other
2. Stale claims: assertions with dates/numbers that may be outdated
3. Knowledge gaps: concepts referenced across 3+ atoms with no dedicated atom
"""

import json
import re
import sqlite3
from datetime import date

from eureka.core.db import atom_table, atom_title_expr
from eureka.core.embeddings import cosine_sim, _unpack_vector


def lint_deep(
    conn: sqlite3.Connection,
    brain_dir,
    llm,
    *,
    max_pairs: int = 50,
    stale_sample: int = 30,
) -> dict:
    """Run LLM-judged lint checks.

    Args:
        conn: open brain.db connection
        brain_dir: path to brain directory
        llm: LLM instance with .generate(prompt) -> str
        max_pairs: max atom pairs to send to LLM for contradiction check
        stale_sample: max atoms to check for staleness

    Returns dict with contradictions, stale_claims, knowledge_gaps, summary.
    """
    contradictions = _find_contradictions(conn, llm, max_pairs=max_pairs)
    stale_claims = _find_stale_claims(conn, llm, sample_size=stale_sample)
    knowledge_gaps = _find_knowledge_gaps(conn)

    return {
        "contradictions": contradictions,
        "stale_claims": stale_claims,
        "knowledge_gaps": knowledge_gaps,
        "summary": {
            "contradictions_found": len(contradictions),
            "stale_claims_found": len(stale_claims),
            "knowledge_gaps_found": len(knowledge_gaps),
            "pairs_checked": min(max_pairs, _count_candidate_pairs(conn)),
            "atoms_checked_staleness": min(stale_sample, _count_atoms_with_body(conn)),
        },
    }


def _count_candidate_pairs(conn: sqlite3.Connection) -> int:
    """Count how many pairs fall in the contradiction band (0.3-0.85)."""
    embeddings = _load_embeddings(conn)
    slugs = sorted(embeddings.keys())
    count = 0
    for i in range(len(slugs)):
        for j in range(i + 1, len(slugs)):
            sim = cosine_sim(embeddings[slugs[i]], embeddings[slugs[j]])
            if 0.3 <= sim <= 0.85:
                count += 1
    return count


def _count_atoms_with_body(conn: sqlite3.Connection) -> int:
    tbl = atom_table(conn)
    return conn.execute(
        f"SELECT COUNT(*) FROM {tbl} WHERE body IS NOT NULL AND body != ''"
    ).fetchone()[0]


def _load_embeddings(conn: sqlite3.Connection) -> dict:
    """Load all embeddings from DB."""
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    out = {}
    for r in rows:
        try:
            out[r["slug"]] = _unpack_vector(r["vector"])
        except Exception:
            continue
    return out


def _find_contradictions(
    conn: sqlite3.Connection,
    llm,
    *,
    max_pairs: int = 50,
) -> list[dict]:
    """Find contradicting atom pairs.

    Pipeline:
    1. Pre-filter: cosine similarity between 0.3 and 0.85 (related but not duplicates)
    2. Batch pairs and ask LLM to judge contradictions
    """
    tbl = atom_table(conn)
    title_expr = atom_title_expr(conn)
    embeddings = _load_embeddings(conn)
    slugs = sorted(embeddings.keys())

    # Pre-filter: find pairs in the contradiction band
    candidates = []
    for i in range(len(slugs)):
        for j in range(i + 1, len(slugs)):
            sim = cosine_sim(embeddings[slugs[i]], embeddings[slugs[j]])
            if 0.3 <= sim <= 0.85:
                candidates.append((slugs[i], slugs[j], sim))

    # Sort by similarity descending (most related first — more likely contradictions)
    candidates.sort(key=lambda x: x[2], reverse=True)
    candidates = candidates[:max_pairs]

    if not candidates:
        return []

    # Load atom bodies for candidates
    needed_slugs = set()
    for a, b, _ in candidates:
        needed_slugs.add(a)
        needed_slugs.add(b)

    atoms = {}
    for slug in needed_slugs:
        row = conn.execute(
            f"SELECT slug, {title_expr} AS title, body FROM {tbl} WHERE slug = ?",
            (slug,),
        ).fetchone()
        if row and row["body"]:
            atoms[slug] = {"title": row["title"], "body": row["body"][:300]}

    # Build batched prompt (batch of 10 at a time to stay under token limits)
    contradictions = []
    batch_size = 10
    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start:batch_start + batch_size]
        pairs_text = []
        valid_pairs = []
        for idx, (a, b, sim) in enumerate(batch):
            if a not in atoms or b not in atoms:
                continue
            pairs_text.append(
                f"Pair {idx + 1}:\n"
                f"  A: [{a}] {atoms[a]['title']}: {atoms[a]['body']}\n"
                f"  B: [{b}] {atoms[b]['title']}: {atoms[b]['body']}"
            )
            valid_pairs.append((a, b, sim))

        if not pairs_text:
            continue

        prompt = (
            "You are a knowledge graph auditor. For each pair of knowledge atoms below, "
            "determine if they CONTRADICT each other — i.e., assert incompatible claims.\n"
            "Disagreement in emphasis or scope is NOT a contradiction.\n"
            "Only flag genuine logical contradictions.\n\n"
            + "\n\n".join(pairs_text)
            + "\n\nRespond with ONLY a JSON array. Each element should be:\n"
            '{"pair": <pair_number>, "contradiction": true/false, "explanation": "brief reason"}\n'
            "If no contradictions exist, return an empty array: []"
        )

        raw = llm.generate(prompt)
        parsed = _parse_json_array(raw)

        if parsed:
            for item in parsed:
                pair_idx = item.get("pair", 0) - 1
                if item.get("contradiction") and 0 <= pair_idx < len(valid_pairs):
                    a, b, sim = valid_pairs[pair_idx]
                    contradictions.append({
                        "atom_a": a,
                        "atom_b": b,
                        "similarity": round(sim, 4),
                        "explanation": item.get("explanation", ""),
                    })

    return contradictions


def _find_stale_claims(
    conn: sqlite3.Connection,
    llm,
    *,
    sample_size: int = 30,
) -> list[dict]:
    """Find atoms with potentially outdated claims.

    Looks for atoms containing dates, numbers, or temporal language,
    then asks LLM to judge if the claims might be stale.
    """
    tbl = atom_table(conn)
    title_expr = atom_title_expr(conn)

    # Find atoms with temporal/numeric content
    temporal_re = re.compile(
        r"\b(20[0-2]\d|as of|currently|recent|latest|now|today|this year"
        r"|last year|\d+%|\$[\d,]+|growing|declining|estimated)\b",
        re.IGNORECASE,
    )

    rows = conn.execute(
        f"SELECT slug, {title_expr} AS title, body, created_at FROM {tbl} "
        "WHERE body IS NOT NULL AND body != ''"
    ).fetchall()

    candidates = []
    for row in rows:
        if temporal_re.search(row["body"] or ""):
            candidates.append({
                "slug": row["slug"],
                "title": row["title"],
                "body": (row["body"] or "")[:400],
                "created_at": row["created_at"],
            })

    candidates = candidates[:sample_size]
    if not candidates:
        return []

    # Batch and ask LLM
    today = date.today().isoformat()
    atoms_text = []
    for idx, c in enumerate(candidates):
        atoms_text.append(
            f"Atom {idx + 1} [{c['slug']}] (created: {c['created_at'] or 'unknown'}):\n"
            f"  Title: {c['title']}\n"
            f"  Body: {c['body']}"
        )

    prompt = (
        f"Today is {today}. You are auditing a knowledge base for stale claims.\n"
        "For each atom below, determine if it contains claims that are likely OUTDATED "
        "— statistics, market data, technology state, or assertions tied to a specific time.\n"
        "Do NOT flag timeless principles, opinions, or conceptual ideas as stale.\n\n"
        + "\n\n".join(atoms_text)
        + "\n\nRespond with ONLY a JSON array. Each element:\n"
        '{"atom": <atom_number>, "stale": true/false, "reason": "what specifically might be outdated"}\n'
        "Only include atoms where stale=true. If none are stale, return: []"
    )

    raw = llm.generate(prompt)
    parsed = _parse_json_array(raw)

    stale = []
    if parsed:
        for item in parsed:
            atom_idx = item.get("atom", 0) - 1
            if item.get("stale") and 0 <= atom_idx < len(candidates):
                c = candidates[atom_idx]
                stale.append({
                    "slug": c["slug"],
                    "title": c["title"],
                    "created_at": c["created_at"],
                    "reason": item.get("reason", ""),
                })

    return stale


def _find_knowledge_gaps(conn: sqlite3.Connection) -> list[dict]:
    """Find concepts mentioned across 3+ atoms that have no dedicated atom.

    Pure computation — extracts [[wikilinks]] and cross-references with existing slugs.
    """
    tbl = atom_table(conn)

    # Get all existing slugs
    existing = {
        r["slug"]
        for r in conn.execute(f"SELECT slug FROM {tbl}").fetchall()
    }

    # Extract all wikilinks from atom bodies
    wikilink_re = re.compile(r"\[\[([^\]]+)\]\]")
    mention_counts: dict[str, set[str]] = {}  # target → set of source slugs

    rows = conn.execute(f"SELECT slug, body FROM {tbl} WHERE body IS NOT NULL").fetchall()
    for row in rows:
        for match in wikilink_re.findall(row["body"] or ""):
            ref = match.strip()
            if ref and ref not in existing:
                mention_counts.setdefault(ref, set()).add(row["slug"])

    # Filter: concepts mentioned in 3+ different atoms
    gaps = []
    for concept, sources in sorted(mention_counts.items(), key=lambda x: len(x[1]), reverse=True):
        if len(sources) >= 3:
            gaps.append({
                "concept": concept,
                "mentioned_in": sorted(sources),
                "mention_count": len(sources),
            })

    return gaps[:20]  # Cap at 20


def _parse_json_array(text: str) -> list | None:
    """Parse a JSON array from LLM response, handling markdown wrapping."""
    # Direct parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Extract from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Try finding first [ ... ] block
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return None
