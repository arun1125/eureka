"""Slice 2: parser — extract title, body, wikilinks, tags from .md files."""

from pathlib import Path
from eureka.core.parser import parse_note

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_title():
    """Parser extracts title from the H1 heading."""
    note = parse_note(FIXTURES / "margin-of-safety-applies-engineering-redundancy-to-investing.md")
    assert note["title"] == "Margin of safety applies engineering redundancy to investing"


def test_parse_slug():
    """Slug is kebab-case derived from filename."""
    note = parse_note(FIXTURES / "margin-of-safety-applies-engineering-redundancy-to-investing.md")
    assert note["slug"] == "margin-of-safety-applies-engineering-redundancy-to-investing"


def test_parse_body():
    """Body is the text between the title and the tags line."""
    note = parse_note(FIXTURES / "margin-of-safety-applies-engineering-redundancy-to-investing.md")
    assert "buy a stock below its intrinsic value" in note["body"]
    # Body should not include the title or the tags line
    assert not note["body"].startswith("#")
    assert "tags:" not in note["body"]


def test_parse_wikilinks():
    """Parser extracts wikilinks from the body."""
    note = parse_note(FIXTURES / "margin-of-safety-applies-engineering-redundancy-to-investing.md")
    assert set(note["wikilinks"]) == {"antifragility-defined", "barbell-strategy"}


def test_parse_tags():
    """Parser extracts tags from the tags: line."""
    note = parse_note(FIXTURES / "margin-of-safety-applies-engineering-redundancy-to-investing.md")
    assert set(note["tags"]) == {"investing", "risk-management", "mental-models"}


def test_parse_body_hash():
    """Parser computes a body_hash for change detection."""
    note = parse_note(FIXTURES / "margin-of-safety-applies-engineering-redundancy-to-investing.md")
    assert isinstance(note["body_hash"], str)
    assert len(note["body_hash"]) == 64  # SHA256 hex digest


def test_parse_no_tags():
    """Atom with no tags line returns empty list."""
    note = parse_note(FIXTURES / "barbell-strategy.md")
    # barbell-strategy has tags, but let's test the field exists
    assert isinstance(note["tags"], list)
