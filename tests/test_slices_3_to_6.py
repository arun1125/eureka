"""Tests for Slices 3-6: enrichment, co-citation, deep mode, paper extraction."""

import json
import sqlite3
import struct
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from eureka.core.db import open_db, ensure_tag, tag_note
from eureka.core.citation_graph import build_reference_stubs, enrich_stubs
from eureka.core.discovery import find_co_citations
from eureka.core.extractor import extract_atoms, parse_extraction_response

FIXTURES = Path(__file__).parent / "fixtures"
PAPER = FIXTURES / "attention-is-all-you-need.pdf"


# --- Helpers ---

def _make_brain(tmp_path):
    """Create an empty brain with DB."""
    bd = tmp_path / "brain"
    bd.mkdir()
    (bd / "atoms").mkdir()
    (bd / "molecules").mkdir()
    conn = open_db(bd / "brain.db")
    return bd, conn


def _insert_atom(conn, slug, title, body, tags=None):
    """Insert an atom into the atoms table."""
    conn.execute(
        "INSERT INTO atoms (slug, title, body, body_hash, word_count) VALUES (?, ?, ?, '', ?)",
        (slug, title, body, len(body.split())),
    )
    if tags:
        for tag_name in tags:
            tid = ensure_tag(conn, tag_name)
            tag_note(conn, slug, tid)


def _insert_edge(conn, source, target):
    conn.execute("INSERT OR IGNORE INTO edges (source, target) VALUES (?, ?)", (source, target))


def _pack_vector(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _insert_embedding(conn, slug, vec):
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (slug, model, vector, updated) VALUES (?, 'test', ?, 0)",
        (slug, _pack_vector(vec)),
    )


# ============================================================
# Slice 3: Semantic Scholar Enrichment
# ============================================================

class TestEnrichStubs:
    """Test enrich_stubs integrating S2 data into stub atoms."""

    def test_enriches_stub_body_with_abstract(self, tmp_path):
        """Enriched stub should have abstract in body."""
        bd, conn = _make_brain(tmp_path)

        # Create a reference stub
        _insert_atom(conn, "attention-is-all-you-need", "Attention Is All You Need",
                      "Authors: Vaswani et al.\nYear: 2017", tags=["reference-stub", "paper"])
        conn.commit()

        # Mock S2 API to return an abstract
        fake_enrichment = [{
            "enriched": True,
            "title": "Attention Is All You Need",
            "abstract": "We propose a new simple network architecture, the Transformer.",
            "authors": ["Vaswani", "Shazeer"],
            "year": 2017,
            "citation_count": 100000,
            "tldr": "Transformers replace RNNs.",
            "doi": "10.5555/3295222.3295349",
            "original_number": 1,
        }]

        with patch("eureka.core.semantic_scholar.enrich_all_references", return_value=fake_enrichment):
            result = enrich_stubs(conn, [])
        assert result["enriched"] == 1
        assert result["not_found"] == 0

        # Verify body was updated
        row = conn.execute("SELECT body FROM atoms WHERE slug = 'attention-is-all-you-need'").fetchone()
        assert "Transformer" in row["body"]
        assert "100000" in row["body"]  # citation count
        conn.close()

    def test_skips_already_enriched(self, tmp_path):
        """Stubs with long bodies (>200 chars) are skipped."""
        bd, conn = _make_brain(tmp_path)
        long_body = "A" * 300
        _insert_atom(conn, "some-paper", "Some Paper", long_body, tags=["reference-stub", "paper"])
        conn.commit()

        with patch("eureka.core.semantic_scholar.enrich_all_references") as mock_enrich:
            result = enrich_stubs(conn, [])
        mock_enrich.assert_not_called()
        assert result["already_enriched"] == 1
        conn.close()

    def test_returns_not_found_for_missing(self, tmp_path):
        """Stubs that S2 can't find are counted as not_found."""
        bd, conn = _make_brain(tmp_path)
        _insert_atom(conn, "obscure-paper", "Obscure Paper", "Year: 2020",
                      tags=["reference-stub", "paper"])
        conn.commit()

        fake_enrichment = [{"enriched": False, "title": "Obscure Paper", "original_number": 1}]
        with patch("eureka.core.semantic_scholar.enrich_all_references", return_value=fake_enrichment):
            result = enrich_stubs(conn, [])
        assert result["not_found"] == 1
        assert result["enriched"] == 0
        conn.close()

    def test_no_stubs_returns_zero(self, tmp_path):
        """Brain with no reference stubs returns zero counts."""
        bd, conn = _make_brain(tmp_path)
        result = enrich_stubs(conn, [])
        assert result["enriched"] == 0
        conn.close()


# ============================================================
# Slice 4: Co-citation Discovery
# ============================================================

class TestCoCitation:
    """Test find_co_citations discovers papers sharing references."""

    def _build_citation_brain(self, tmp_path):
        """Build a brain with 2 papers sharing 3 references.

        paper-a → ref-1, ref-2, ref-3
        paper-b → ref-2, ref-3, ref-4
        Shared: ref-2, ref-3 (≥2)
        paper-a and paper-b are NOT directly linked.
        """
        bd, conn = _make_brain(tmp_path)

        # Paper atoms
        _insert_atom(conn, "paper-a", "Paper A", "Findings from paper A")
        _insert_atom(conn, "paper-b", "Paper B", "Findings from paper B")

        # Reference stubs
        for i in range(1, 5):
            _insert_atom(conn, f"ref-{i}", f"Reference {i}", f"Reference paper {i}",
                          tags=["reference-stub", "paper"])

        # Citation edges: paper → reference
        _insert_edge(conn, "paper-a", "ref-1")
        _insert_edge(conn, "paper-a", "ref-2")
        _insert_edge(conn, "paper-a", "ref-3")
        _insert_edge(conn, "paper-b", "ref-2")
        _insert_edge(conn, "paper-b", "ref-3")
        _insert_edge(conn, "paper-b", "ref-4")

        # Embeddings — make paper-a and paper-b somewhat different
        import numpy as np
        rng = np.random.RandomState(42)
        for slug in ["paper-a", "paper-b", "ref-1", "ref-2", "ref-3", "ref-4"]:
            vec = rng.randn(384).astype(float).tolist()
            _insert_embedding(conn, slug, vec)

        conn.commit()
        return bd, conn

    def test_finds_co_citation_pair(self, tmp_path):
        """Two papers sharing ≥2 references and not directly linked → co-citation candidate."""
        bd, conn = self._build_citation_brain(tmp_path)
        embeddings = {}
        for row in conn.execute("SELECT slug, vector FROM embeddings").fetchall():
            dim = len(row["vector"]) // 4
            embeddings[row["slug"]] = list(struct.unpack(f"{dim}f", row["vector"]))

        candidates = find_co_citations(conn, embeddings, min_shared=2)
        assert len(candidates) >= 1
        c = candidates[0]
        assert c["method"] == "co-citation"
        assert c["shared_references"] >= 2
        # Should contain both papers
        atom_set = set(c["atoms"])
        assert "paper-a" in atom_set
        assert "paper-b" in atom_set
        conn.close()

    def test_ignores_directly_linked_pairs(self, tmp_path):
        """Papers that are directly linked should NOT appear as co-citation voids."""
        bd, conn = self._build_citation_brain(tmp_path)
        # Add direct edge between paper-a and paper-b
        _insert_edge(conn, "paper-a", "paper-b")
        conn.commit()

        embeddings = {}
        for row in conn.execute("SELECT slug, vector FROM embeddings").fetchall():
            dim = len(row["vector"]) // 4
            embeddings[row["slug"]] = list(struct.unpack(f"{dim}f", row["vector"]))

        candidates = find_co_citations(conn, embeddings, min_shared=2)
        # Should not find the pair since they're directly linked
        for c in candidates:
            atom_set = set(c["atoms"])
            assert not ({"paper-a", "paper-b"} <= atom_set)
        conn.close()

    def test_no_stubs_returns_empty(self, tmp_path):
        """Brain with no reference stubs returns empty list."""
        bd, conn = _make_brain(tmp_path)
        _insert_atom(conn, "lonely-atom", "Lonely", "Just me here")
        conn.commit()
        candidates = find_co_citations(conn, {}, min_shared=2)
        assert candidates == []
        conn.close()

    def test_min_shared_threshold(self, tmp_path):
        """Setting min_shared=3 should filter out pairs with only 2 shared refs."""
        bd, conn = self._build_citation_brain(tmp_path)
        embeddings = {}
        for row in conn.execute("SELECT slug, vector FROM embeddings").fetchall():
            dim = len(row["vector"]) // 4
            embeddings[row["slug"]] = list(struct.unpack(f"{dim}f", row["vector"]))

        # Only 2 shared refs → min_shared=3 should find nothing
        candidates = find_co_citations(conn, embeddings, min_shared=3)
        assert len(candidates) == 0
        conn.close()


# ============================================================
# Slice 5: Deep Mode (tested via integration test pattern)
# ============================================================

class TestDeepMode:
    """Test --deep flag on ingest triggers recursive fetch."""

    def test_deep_flag_accepted(self, tmp_path):
        """run_ingest accepts deep=True without crashing (even if no refs have arXiv IDs)."""
        from eureka.commands.ingest import run_ingest
        from eureka.readers.paper import PaperReader

        bd = tmp_path / "brain"
        bd.mkdir()
        (bd / "atoms").mkdir()
        conn = open_db(bd / "brain.db")
        conn.close()

        class FakeLLM:
            def generate(self, prompt):
                return "# Test atom\n\nBody text.\n\ntags: test\n"

        def fake_ensure_embeddings(conn, brain_dir, force=False):
            pass  # skip real embedding

        with patch("eureka.commands.ingest.get_llm", return_value=FakeLLM()), \
             patch("eureka.commands.ingest.detect_reader", return_value=PaperReader()), \
             patch("eureka.core.embeddings.ensure_embeddings", fake_ensure_embeddings):
            # deep=True but no arXiv refs → should complete without error
            run_ingest(str(PAPER), str(bd), deep=True)

        conn = open_db(bd / "brain.db")
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        conn.close()


# ============================================================
# Slice 6: Paper-specific Extraction Prompt
# ============================================================

class TestPaperExtraction:
    """Test paper-specific extraction prompt produces claim-typed atoms."""

    def test_paper_prompt_includes_claim_types(self):
        """The paper extraction prompt should mention finding, method, hypothesis, etc."""
        from eureka.core.extractor import PAPER_EXTRACTION_PROMPT
        assert "finding" in PAPER_EXTRACTION_PROMPT
        assert "method" in PAPER_EXTRACTION_PROMPT
        assert "hypothesis" in PAPER_EXTRACTION_PROMPT
        assert "limitation" in PAPER_EXTRACTION_PROMPT
        assert "open-question" in PAPER_EXTRACTION_PROMPT

    def test_extract_atoms_uses_paper_prompt(self):
        """When source_type='paper', the LLM receives the paper-specific prompt."""
        received_prompts = []

        class SpyLLM:
            def generate(self, prompt):
                received_prompts.append(prompt)
                return "# Finding one\n\nResult.\n\ntags: finding, test\n"

        extract_atoms(["Some paper text"], [], SpyLLM(), source_type="paper")
        assert len(received_prompts) == 1
        assert "empirical results" in received_prompts[0]  # from paper prompt
        assert "claim type" in received_prompts[0].lower() or "finding" in received_prompts[0]

    def test_extract_atoms_uses_default_prompt_for_books(self):
        """When source_type='book', the default prompt is used."""
        received_prompts = []

        class SpyLLM:
            def generate(self, prompt):
                received_prompts.append(prompt)
                return "# Concept one\n\nExplanation.\n\ntags: test\n"

        extract_atoms(["Some book text"], [], SpyLLM(), source_type="book")
        assert len(received_prompts) == 1
        assert "empirical results" not in received_prompts[0]

    def test_parse_paper_atoms_with_claim_tags(self):
        """Parse response with claim-type tags."""
        response = """# Transformer achieves 28.4 BLEU on WMT English-to-German

The Transformer model achieves 28.4 BLEU on the WMT 2014 English-to-German
translation task, outperforming all previously published models including ensembles.

tags: finding, translation, nlp

---

# Future work should explore local attention for long sequences

The authors note that self-attention has O(n²) complexity and suggest that
restricted attention mechanisms could handle very long sequences more efficiently.

tags: open-question, attention, efficiency"""

        atoms = parse_extraction_response(response)
        assert len(atoms) == 2
        assert "finding" in atoms[0]["tags"]
        assert atoms[0]["slug"] == "transformer-achieves-284-bleu-on-wmt-english-to-german"
        assert "open-question" in atoms[1]["tags"]
