"""PDFReader — reads PDF files into page-based chunks."""

from pathlib import Path


class PDFReader:
    """Read a PDF and split into page-based chunks."""

    def read(self, source_path: str) -> dict:
        """Return {"title": str, "type": "pdf", "chunks": list[str]}."""
        import pymupdf

        path = Path(source_path)
        doc = pymupdf.open(str(path))
        title = doc.metadata.get("title") or path.stem.replace("-", " ").replace("_", " ").title()

        # Group pages into ~2000 char chunks
        chunks = []
        current = ""
        for page in doc:
            text = page.get_text().strip()
            if not text:
                continue
            if len(current) + len(text) > 2000:
                if current:
                    chunks.append(current)
                current = text
            else:
                current += "\n\n" + text if current else text
        if current:
            chunks.append(current)

        doc.close()
        return {"title": title, "type": "pdf", "chunks": chunks}
