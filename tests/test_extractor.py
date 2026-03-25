"""Slice 5: extractor — LLM extraction with mock, full ingest pipeline."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from eureka.core.extractor import extract_atoms, parse_extraction_response

FIXTURES = Path(__file__).parent / "fixtures"

# Canned LLM response — what a real LLM would return
MOCK_LLM_RESPONSE = """# Energy is mathematical bookkeeping not a description of mechanism

Energy conservation is not about understanding what energy IS — it's a
bookkeeping trick. You track a number across transformations and it never
changes. The power is in the accounting, not the explanation. [[conservation-principles]]

tags: physics, mental-models
---
# Nature speaks mathematics whether we like it or not

Mathematics was invented for its own sake, yet it turns out to be the
language nature uses. Every attempt to describe physics without math
produces only a vague shadow. This is one of the great unsolved mysteries. [[compression-as-understanding]]

tags: physics, mathematics
---
# The same laws govern heaven and earth

Newton's key insight was not the formula — it was that celestial bodies
follow the same rules as an apple falling from a tree. There is no
separate physics for the heavens. [[domain-dependence]]

tags: physics, mental-models
"""


def test_parse_extraction_response():
    """parse_extraction_response splits LLM output into atom dicts."""
    atoms = parse_extraction_response(MOCK_LLM_RESPONSE)
    assert len(atoms) == 3
    assert atoms[0]["title"] == "Energy is mathematical bookkeeping not a description of mechanism"
    assert "bookkeeping trick" in atoms[0]["body"]
    assert "physics" in atoms[0]["tags"]
    assert "mental-models" in atoms[0]["tags"]
    assert "conservation-principles" in atoms[0]["wikilinks"]


def test_parse_extraction_response_generates_slugs():
    """Each parsed atom has a kebab-case slug derived from title."""
    atoms = parse_extraction_response(MOCK_LLM_RESPONSE)
    assert atoms[0]["slug"] == "energy-is-mathematical-bookkeeping-not-a-description-of-mechanism"
    assert atoms[2]["slug"] == "the-same-laws-govern-heaven-and-earth"


def test_extract_atoms_calls_llm():
    """extract_atoms sends chunks to the LLM and returns parsed atoms."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = MOCK_LLM_RESPONSE

    chunks = ["chunk 1 about energy", "chunk 2 about math"]
    atoms = extract_atoms(chunks, existing_tags=["physics"], llm=mock_llm)

    assert mock_llm.generate.called
    assert len(atoms) == 3
    assert all("slug" in a for a in atoms)


def test_extract_atoms_passes_existing_tags():
    """extract_atoms includes existing tags in the prompt for the LLM."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = MOCK_LLM_RESPONSE

    extract_atoms(["chunk"], existing_tags=["physics", "investing"], llm=mock_llm)

    # The prompt sent to the LLM should mention existing tags
    call_args = mock_llm.generate.call_args
    prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "physics" in prompt
    assert "investing" in prompt


def run_eureka(*args):
    result = subprocess.run(
        [sys.executable, "-m", "eureka.cli", *args],
        capture_output=True, text=True,
    )
    return result, json.loads(result.stdout) if result.stdout.strip() else None


def test_full_ingest_with_mock_llm(tmp_path, monkeypatch):
    """Full ingest pipeline: chunk → extract → write .md → index → embed → link."""
    brain_dir = tmp_path / "mybrain"
    run_eureka("init", str(brain_dir))

    # Mock the LLM at the module level
    mock_llm = MagicMock()
    mock_llm.generate.return_value = MOCK_LLM_RESPONSE

    from eureka.commands import ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "get_llm", lambda brain_dir: mock_llm)

    # Mock embeddings to avoid needing GEMINI_API_KEY
    from eureka.core.embeddings import _deterministic_embed
    original_ensure = ingest_mod.ensure_embeddings if hasattr(ingest_mod, "ensure_embeddings") else None
    import eureka.core.embeddings as _emb_mod
    _orig_ensure = _emb_mod.ensure_embeddings
    monkeypatch.setattr(_emb_mod, "ensure_embeddings",
                        lambda conn, bd, force=False, embed_fn=None: _orig_ensure(conn, bd, force=force, embed_fn=_deterministic_embed))

    # Call in-process so monkeypatch takes effect (subprocess can't see it)
    from io import StringIO

    buf = StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    ingest_mod.run_ingest(str(FIXTURES / "sample_source.txt"), str(brain_dir))

    output = json.loads(buf.getvalue().strip())
    assert output["ok"] is True
    assert output["data"]["atoms_created"] >= 1

    # Atoms should exist as .md files
    atom_files = list((brain_dir / "atoms").glob("*.md"))
    assert len(atom_files) >= 1
