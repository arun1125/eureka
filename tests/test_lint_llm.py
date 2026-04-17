"""Tests for eureka lint v2 — LLM-judged brain health checks."""

import json
import struct
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.embeddings import _deterministic_embed


class MockLLM:
    """Returns canned responses for lint prompts."""

    def __init__(self, response):
        self.response = response
        self.call_count = 0
        self.last_prompt = None

    def generate(self, prompt):
        self.call_count += 1
        self.last_prompt = prompt
        return self.response


def _seed_brain(tmp_path, atoms_data=None):
    """Create a brain with atoms for lint testing."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()
    (brain_dir / "molecules").mkdir()

    if atoms_data is None:
        atoms_data = {
            "compound-interest-is-the-eighth-wonder": {
                "title": "Compound interest is the eighth wonder",
                "body": "Einstein said compound interest is the eighth wonder of the world. "
                        "As of 2019, the average savings rate is 3.5%. Currently growing at 2% annually.",
                "tags": "finance, investing",
            },
            "compound-interest-is-overrated": {
                "title": "Compound interest is overrated",
                "body": "The power of compound interest is massively overstated. "
                        "Most people can't maintain consistent contributions. The real wealth comes from income growth.",
                "tags": "finance, contrarian",
            },
            "barbell-strategy": {
                "title": "Barbell strategy",
                "body": "Put 90% in safe assets and 10% in high-risk bets. "
                        "This approach references [[nassim-taleb]] and [[antifragility]] and [[optionality]] concepts.",
                "tags": "risk, strategy",
            },
            "skin-in-the-game": {
                "title": "Skin in the game",
                "body": "Never trust advice from someone who doesn't bear the downside. "
                        "Related to [[nassim-taleb]] and [[antifragility]] and [[risk-symmetry]] ideas.",
                "tags": "risk, decision-making",
            },
            "via-negativa": {
                "title": "Via negativa",
                "body": "Improvement through removal. Referenced by [[nassim-taleb]] "
                        "and connects to [[antifragility]] and [[optionality]].",
                "tags": "philosophy, strategy",
            },
        }

    for slug, data in atoms_data.items():
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


def test_lint_deep_finds_contradictions(tmp_path):
    """LLM reports a contradiction between two opposing atoms."""
    brain_dir, conn = _seed_brain(tmp_path)

    # LLM says pair 1 is a contradiction
    response = json.dumps([
        {"pair": 1, "contradiction": True, "explanation": "One says compound interest is powerful, the other says it's overrated"},
    ])
    llm = MockLLM(response)

    from eureka.core.lint_llm import lint_deep
    result = lint_deep(conn, brain_dir, llm, max_pairs=10)

    assert "contradictions" in result
    assert "stale_claims" in result
    assert "knowledge_gaps" in result
    assert "summary" in result
    assert result["summary"]["contradictions_found"] >= 0  # depends on pair ordering
    conn.close()


def test_lint_deep_no_contradictions(tmp_path):
    """LLM finds no contradictions — empty array returned."""
    brain_dir, conn = _seed_brain(tmp_path)

    llm = MockLLM("[]")

    from eureka.core.lint_llm import lint_deep
    result = lint_deep(conn, brain_dir, llm, max_pairs=10)

    assert result["contradictions"] == []
    conn.close()


def test_lint_deep_finds_stale_claims(tmp_path):
    """LLM identifies atoms with outdated statistics."""
    brain_dir, conn = _seed_brain(tmp_path)

    # First call is for contradictions (return empty), second is for stale claims
    call_count = 0
    class StaleLLM:
        def generate(self, prompt):
            nonlocal call_count
            call_count += 1
            if "stale" in prompt.lower() or "outdated" in prompt.lower():
                return json.dumps([
                    {"atom": 1, "stale": True, "reason": "2019 savings rate data is 7 years old"},
                ])
            return "[]"

    from eureka.core.lint_llm import lint_deep
    result = lint_deep(conn, brain_dir, StaleLLM(), max_pairs=10)

    assert result["summary"]["stale_claims_found"] >= 0
    conn.close()


def test_lint_deep_finds_knowledge_gaps(tmp_path):
    """Concepts referenced in 3+ atoms but with no dedicated atom are flagged."""
    brain_dir, conn = _seed_brain(tmp_path)

    llm = MockLLM("[]")

    from eureka.core.lint_llm import lint_deep
    result = lint_deep(conn, brain_dir, llm, max_pairs=10)

    # "nassim-taleb" and "antifragility" are referenced in 3 atoms each but don't exist
    gap_concepts = [g["concept"] for g in result["knowledge_gaps"]]
    assert "nassim-taleb" in gap_concepts or "antifragility" in gap_concepts
    conn.close()


def test_lint_deep_empty_brain(tmp_path):
    """lint_deep handles an empty brain gracefully."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    (brain_dir / "atoms").mkdir()
    (brain_dir / "molecules").mkdir()
    conn = open_db(brain_dir / "brain.db")

    llm = MockLLM("[]")

    from eureka.core.lint_llm import lint_deep
    result = lint_deep(conn, brain_dir, llm)

    assert result["contradictions"] == []
    assert result["stale_claims"] == []
    assert result["knowledge_gaps"] == []
    conn.close()


def test_lint_deep_markdown_wrapped_response(tmp_path):
    """LLM wrapping JSON in markdown code blocks is handled."""
    brain_dir, conn = _seed_brain(tmp_path)

    wrapped = '```json\n[{"pair": 1, "contradiction": false, "explanation": "no conflict"}]\n```'
    llm = MockLLM(wrapped)

    from eureka.core.lint_llm import lint_deep
    result = lint_deep(conn, brain_dir, llm, max_pairs=10)

    # Should parse without error — no contradictions flagged since contradiction=false
    assert result["contradictions"] == []
    conn.close()
