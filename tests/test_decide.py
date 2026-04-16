"""Tests for eureka decide — structured decision-making against the brain."""

import json
import struct
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.embeddings import _deterministic_embed


VALID_DECISION = json.dumps({
    "for_arguments": [
        "Lower cost of living allows runway to last 2x longer",
        "Warm climate improves daily energy and focus",
    ],
    "against_arguments": [
        "Time zone gap makes real-time collaboration harder",
        "Visa uncertainty adds administrative overhead",
    ],
    "tensions": [
        "Optimizing for cost conflicts with optimizing for network proximity",
    ],
    "unknowns": [
        "Will internet reliability support daily video calls?",
    ],
    "recommendation": "Move, but keep a 3-month return buffer. The cost savings outweigh the collaboration friction for solo work.",
})


class MockLLM:
    """Returns a canned response and captures the prompt for inspection."""

    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def generate(self, prompt):
        self.last_prompt = prompt
        return self.response


def _seed_brain(tmp_path):
    """Create a brain with a few atoms so decide has context to pull from."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()
    (brain_dir / "molecules").mkdir()

    atoms = {
        "remote-work-unlocks-geographic-arbitrage": {
            "title": "Remote work unlocks geographic arbitrage",
            "body": "If your income is location-independent, moving to a cheaper city is a free raise.",
            "tags": "lifestyle, money",
        },
        "barbell-strategy": {
            "title": "Barbell strategy",
            "body": "Put 90% in safe assets and 10% in high-risk bets. Avoid the middle.",
            "tags": "risk, strategy",
        },
        "skin-in-the-game": {
            "title": "Skin in the game",
            "body": "Never trust advice from someone who doesn't bear the downside of being wrong.",
            "tags": "risk, decision-making",
        },
    }
    for slug, data in atoms.items():
        md = f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    from eureka.core.linker import link_all
    link_all(conn)

    return brain_dir, conn


def _load_embeddings(conn):
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    emb = {}
    for r in rows:
        dim = len(r["vector"]) // 4
        emb[r["slug"]] = list(struct.unpack(f"{dim}f", r["vector"]))
    return emb


def test_decide_basic(tmp_path, monkeypatch):
    """decide returns all expected fields when LLM returns valid JSON."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    llm = MockLLM(VALID_DECISION)

    from eureka.core.decide import decide
    result = decide("Should I move to Bangkok?", conn, embeddings, llm, brain_dir=brain_dir)

    assert result["question"] == "Should I move to Bangkok?"
    assert len(result["for_arguments"]) == 2
    assert len(result["against_arguments"]) == 2
    assert len(result["tensions"]) == 1
    assert len(result["unknowns"]) == 1
    assert "recommendation" in result
    assert len(result["atoms_consulted"]) > 0


def test_decide_no_file_back(tmp_path, monkeypatch):
    """file_back=False produces a result without writing a molecule to the DB."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    llm = MockLLM(VALID_DECISION)

    from eureka.core.decide import decide
    result = decide(
        "Should I move to Bangkok?", conn, embeddings, llm, file_back=False,
    )

    assert result["molecule_slug"] is None
    mol_count = conn.execute("SELECT count(*) FROM molecules").fetchone()[0]
    assert mol_count == 0


def test_decide_file_back_writes_molecule(tmp_path, monkeypatch):
    """file_back=True (default) writes a molecule to the DB."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    llm = MockLLM(VALID_DECISION)

    from eureka.core.decide import decide
    result = decide("Should I move to Bangkok?", conn, embeddings, llm, brain_dir=brain_dir)

    assert result["molecule_slug"] is not None
    row = conn.execute(
        "SELECT * FROM molecules WHERE slug = ?", (result["molecule_slug"],)
    ).fetchone()
    assert row is not None


def test_decide_with_context(tmp_path, monkeypatch):
    """Extra context string is passed through to the LLM prompt."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    llm = MockLLM(VALID_DECISION)

    from eureka.core.decide import decide
    decide(
        "Should I move to Bangkok?",
        conn, embeddings, llm,
        context="I'm a Canadian citizen with a remote job paying CAD.",
        brain_dir=brain_dir,
    )

    assert "Canadian citizen" in llm.last_prompt


def test_decide_markdown_wrapped_json(tmp_path, monkeypatch):
    """LLM wrapping JSON in a markdown code block is handled gracefully."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)
    wrapped = f"```json\n{VALID_DECISION}\n```"
    llm = MockLLM(wrapped)

    from eureka.core.decide import decide
    result = decide("Should I move to Bangkok?", conn, embeddings, llm, brain_dir=brain_dir)

    assert len(result["for_arguments"]) == 2
    assert "recommendation" in result


def test_decide_empty_brain(tmp_path, monkeypatch):
    """decide works even with an empty brain (no atoms/embeddings)."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    (brain_dir / "molecules").mkdir()
    conn = open_db(brain_dir / "brain.db")

    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    llm = MockLLM(VALID_DECISION)

    from eureka.core.decide import decide
    result = decide("Should I move to Bangkok?", conn, {}, llm)

    assert result["question"] == "Should I move to Bangkok?"
    assert result["atoms_consulted"] == []
    assert "recommendation" in result
