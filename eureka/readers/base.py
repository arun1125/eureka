"""Reader detection — route a source string to the right reader."""

from pathlib import Path

from eureka.readers.text import TextReader
from eureka.readers.url import URLReader
from eureka.readers.youtube import YouTubeReader
from eureka.readers.pdf import PDFReader
from eureka.readers.epub import EPUBReader


def detect_reader(source_str: str):
    """Examine source_str and return the appropriate reader instance."""
    # URLs first
    if source_str.startswith(("http://", "https://")):
        if "youtube.com" in source_str or "youtu.be" in source_str:
            return YouTubeReader()
        return URLReader()

    # File paths
    suffix = Path(source_str).suffix.lower()
    if suffix in (".txt", ".md"):
        return TextReader()
    if suffix == ".pdf":
        return PDFReader()
    if suffix == ".epub":
        return EPUBReader()

    raise ValueError(f"No reader found for: {source_str}")
