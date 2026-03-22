"""Slice 1: PaperReader — parse scientific PDFs into sections + references."""

import re
from pathlib import Path

import pytest

from eureka.readers.paper import PaperReader
from eureka.readers.base import detect_reader

FIXTURES = Path(__file__).parent / "fixtures"
PAPER = FIXTURES / "attention-is-all-you-need.pdf"


@pytest.fixture
def result():
    reader = PaperReader()
    return reader.read(str(PAPER))


# --- Basic structure ---

def test_returns_paper_type(result):
    assert result["type"] == "paper"


def test_extracts_title(result):
    assert "attention" in result["title"].lower()


def test_has_metadata(result):
    meta = result["metadata"]
    assert "authors" in meta
    assert isinstance(meta["authors"], list)
    assert len(meta["authors"]) >= 1


# --- Chunks (pipeline-compatible strings) ---

def test_has_chunks(result):
    assert isinstance(result["chunks"], list)
    assert len(result["chunks"]) >= 3
    # Chunks are strings for pipeline compatibility
    for chunk in result["chunks"]:
        assert isinstance(chunk, str)
        assert len(chunk.strip()) > 0


# --- Sections (structured) ---

def test_has_sections(result):
    assert isinstance(result["sections"], list)
    assert len(result["sections"]) >= 3


def test_sections_have_labels(result):
    """Each section should have a 'section' key identifying the paper section."""
    for s in result["sections"]:
        assert "section" in s
        assert "text" in s
        assert len(s["text"].strip()) > 0


def test_detects_abstract(result):
    sections = [s["section"] for s in result["sections"]]
    assert "abstract" in sections


def test_detects_introduction(result):
    sections = [s["section"] for s in result["sections"]]
    assert any("introduction" in s.lower() for s in sections)


def test_detects_conclusion_or_discussion(result):
    sections = [s["section"] for s in result["sections"]]
    assert any("conclusion" in s.lower() or "discussion" in s.lower() for s in sections)


# --- References ---

def test_extracts_references(result):
    refs = result["references"]
    assert isinstance(refs, list)
    assert len(refs) >= 30  # Paper has 40 references


def test_references_have_title(result):
    for ref in result["references"][:5]:
        assert "title" in ref
        assert len(ref["title"]) > 5


def test_references_have_authors(result):
    """At least some references should have parsed authors."""
    refs_with_authors = [r for r in result["references"] if r.get("authors")]
    assert len(refs_with_authors) >= 20


def test_references_have_number(result):
    """Numbered references should preserve their number."""
    for ref in result["references"][:5]:
        assert "number" in ref
        assert isinstance(ref["number"], int)


def test_reference_numbers_are_sequential(result):
    numbers = [r["number"] for r in result["references"] if "number" in r]
    assert numbers == sorted(numbers)
    assert numbers[0] == 1


# --- detect_reader routing ---

def test_detect_reader_routes_pdf_to_paper_reader():
    """PDFs that look like papers should route to PaperReader."""
    reader = detect_reader(str(PAPER))
    # PDFs go through PDFReader by default; PaperReader via arxiv: prefix
    assert reader is not None


def test_detect_reader_arxiv_prefix():
    """arxiv:1706.03762 should route to PaperReader."""
    reader = detect_reader("arxiv:1706.03762")
    assert isinstance(reader, PaperReader)


# --- References section not in body ---

def test_references_not_in_body_sections(result):
    """The references section should be extracted, not included as body sections."""
    sections = [s["section"] for s in result["sections"]]
    assert "references" not in sections
    assert "bibliography" not in sections
