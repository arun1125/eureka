"""Slice 4: readers — detect source type, chunk text."""

from pathlib import Path

from eureka.readers.base import detect_reader
from eureka.readers.text import TextReader

FIXTURES = Path(__file__).parent / "fixtures"


def test_text_reader_returns_chunks():
    """TextReader splits a .txt file into chunks."""
    reader = TextReader()
    result = reader.read(str(FIXTURES / "sample_source.txt"))
    assert result["title"] is not None
    assert result["type"] == "text"
    assert isinstance(result["chunks"], list)
    assert len(result["chunks"]) > 0
    # Each chunk is a non-empty string
    for chunk in result["chunks"]:
        assert isinstance(chunk, str)
        assert len(chunk.strip()) > 0


def test_text_reader_chunks_are_reasonable_size():
    """Chunks should be roughly paragraph-sized, not single lines or whole file."""
    reader = TextReader()
    result = reader.read(str(FIXTURES / "sample_source.txt"))
    # With our sample, we should get multiple chunks
    assert len(result["chunks"]) >= 2
    # No chunk should be the entire file
    full_text = (FIXTURES / "sample_source.txt").read_text()
    for chunk in result["chunks"]:
        assert len(chunk) < len(full_text)


def test_detect_reader_text():
    """detect_reader returns TextReader for .txt files."""
    reader = detect_reader(str(FIXTURES / "sample_source.txt"))
    assert isinstance(reader, TextReader)


def test_detect_reader_markdown():
    """detect_reader returns TextReader for .md files."""
    reader = detect_reader(str(FIXTURES / "barbell-strategy.md"))
    assert isinstance(reader, TextReader)


def test_detect_reader_url():
    """detect_reader identifies URLs."""
    reader = detect_reader("https://example.com/article")
    assert reader is not None
    assert reader.__class__.__name__ == "URLReader"


def test_detect_reader_youtube():
    """detect_reader identifies YouTube URLs."""
    reader = detect_reader("https://www.youtube.com/watch?v=abc123")
    assert reader is not None
    assert reader.__class__.__name__ == "YouTubeReader"
