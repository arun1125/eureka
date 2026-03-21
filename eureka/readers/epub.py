"""EPUBReader — reads EPUB files into chapter-based chunks."""

from pathlib import Path


class EPUBReader:
    """Read an EPUB and split into chapter-based chunks."""

    def read(self, source_path: str) -> dict:
        """Return {"title": str, "type": "epub", "chunks": list[str]}."""
        import zipfile
        import re

        path = Path(source_path)
        title = path.stem.replace("-", " ").replace("_", " ").title()

        chunks = []
        with zipfile.ZipFile(str(path), "r") as zf:
            for name in zf.namelist():
                if not name.endswith((".html", ".xhtml", ".htm")):
                    continue
                raw = zf.read(name).decode("utf-8", errors="ignore")
                # Strip HTML tags
                text = re.sub(r"<[^>]+>", " ", raw)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) < 50:
                    continue

                # Split long chapters into ~2000 char chunks
                while len(text) > 2000:
                    # Find a sentence boundary near 2000
                    cut = text.rfind(". ", 1500, 2000)
                    if cut == -1:
                        cut = 2000
                    else:
                        cut += 1  # include the period
                    chunks.append(text[:cut].strip())
                    text = text[cut:].strip()
                if text:
                    chunks.append(text)

        return {"title": title, "type": "epub", "chunks": chunks}
