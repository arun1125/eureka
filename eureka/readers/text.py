"""TextReader — reads .txt and .md files into paragraph-based chunks."""

from pathlib import Path


class TextReader:
    """Read a text/markdown file and split into paragraph chunks."""

    def read(self, source_path: str) -> dict:
        """Return {"title": str, "type": "text", "chunks": list[str]}."""
        path = Path(source_path)
        text = path.read_text(encoding="utf-8")
        title = path.stem.replace("-", " ").replace("_", " ").title()
        chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
        return {"title": title, "type": "text", "chunks": chunks}
