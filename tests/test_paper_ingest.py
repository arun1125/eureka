"""Slice 2: Paper ingest — reference stubs + citation edges."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from eureka.core.db import open_db
from eureka.commands.ingest import run_ingest
from eureka.readers.paper import PaperReader

FIXTURES = Path(__file__).parent / "fixtures"
PAPER = FIXTURES / "attention-is-all-you-need.pdf"


@pytest.fixture
def brain_dir(tmp_path):
    """Create an initialized brain dir."""
    bd = tmp_path / "brain"
    bd.mkdir()
    (bd / "atoms").mkdir()
    conn = open_db(bd / "brain.db")
    conn.close()
    return bd


class FakeLLM:
    """Returns canned atoms for testing."""
    def generate(self, prompt: str) -> str:
        return """# Attention mechanism replaces recurrence entirely

The Transformer architecture shows that attention mechanisms alone, without
recurrence or convolution, can achieve state-of-the-art results on sequence
transduction tasks. This eliminates the sequential bottleneck of RNNs.

tags: attention, transformer, architecture

---

# Multi-head attention captures different representation subspaces

Multi-head attention allows the model to jointly attend to information from
different representation subspaces at different positions, which a single
attention head cannot do effectively.

tags: attention, multi-head, representation"""


@pytest.fixture
def ingested_brain(brain_dir):
    """Ingest the paper into a brain dir."""
    with patch("eureka.commands.ingest.get_llm", return_value=FakeLLM()), \
         patch("eureka.commands.ingest.detect_reader", return_value=PaperReader()):
        run_ingest(str(PAPER), str(brain_dir))
    return brain_dir


def test_source_created(ingested_brain):
    conn = open_db(ingested_brain / "brain.db")
    row = conn.execute("SELECT * FROM sources WHERE type = 'paper'").fetchone()
    assert row is not None
    assert "attention" in row["title"].lower()
    conn.close()


def test_atoms_created_from_extraction(ingested_brain):
    """LLM-extracted atoms should exist as .md files."""
    atoms = list((ingested_brain / "atoms").glob("*.md"))
    assert len(atoms) >= 2  # FakeLLM produces 2 atoms


def test_reference_stubs_created(ingested_brain):
    """Each reference should become a stub atom in the DB."""
    conn = open_db(ingested_brain / "brain.db")
    # Reference stubs are tagged with 'reference-stub'
    stub_count = conn.execute(
        "SELECT COUNT(*) FROM atoms a JOIN note_tags nt ON a.slug = nt.slug "
        "JOIN tags t ON nt.tag_id = t.id WHERE t.name = 'reference-stub'"
    ).fetchone()[0]
    assert stub_count >= 30  # Paper has 40 references
    conn.close()


def test_citation_edges_exist(ingested_brain):
    """Citation edges should connect the paper's atoms to reference stubs."""
    conn = open_db(ingested_brain / "brain.db")
    # Count edges where target is a reference stub
    edge_count = conn.execute(
        "SELECT COUNT(*) FROM edges e "
        "JOIN note_tags nt ON e.target = nt.slug "
        "JOIN tags t ON nt.tag_id = t.id "
        "WHERE t.name = 'reference-stub'"
    ).fetchone()[0]
    assert edge_count >= 30
    conn.close()


def test_reference_stub_has_title(ingested_brain):
    """Reference stubs should have the paper title as their atom title."""
    conn = open_db(ingested_brain / "brain.db")
    stub = conn.execute(
        "SELECT a.title FROM atoms a JOIN note_tags nt ON a.slug = nt.slug "
        "JOIN tags t ON nt.tag_id = t.id WHERE t.name = 'reference-stub' LIMIT 1"
    ).fetchone()
    assert stub is not None
    assert len(stub["title"]) > 5
    conn.close()


def test_idempotent_reingest(ingested_brain):
    """Re-ingesting the same paper should not duplicate stubs."""
    conn = open_db(ingested_brain / "brain.db")
    count_before = conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]
    conn.close()

    with patch("eureka.commands.ingest.get_llm", return_value=FakeLLM()), \
         patch("eureka.commands.ingest.detect_reader", return_value=PaperReader()):
        run_ingest(str(PAPER), str(ingested_brain))

    conn = open_db(ingested_brain / "brain.db")
    count_after = conn.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]
    conn.close()
    assert count_after == count_before
