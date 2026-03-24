"""PaperReader — parse scientific PDFs into sections + references."""

import re
import tempfile
import urllib.request
from pathlib import Path


# Common section headers in scientific papers (case-insensitive)
_SECTION_PATTERNS = [
    # Numbered sections: "1 Introduction", "2.1 Encoder"
    re.compile(r"^(\d+(?:\.\d+)*)\s+([A-Z][A-Za-z\s:,\-]+)$"),
    # Unnumbered all-caps or title-case: "Abstract", "METHODS", "Introduction"
    re.compile(r"^(Abstract|Introduction|Background|Related Work|Methods?|"
               r"Methodology|Model|Approach|Architecture|Experiments?|"
               r"Results?|Discussion|Conclusion|Conclusions|"
               r"Limitations|Future Work|Acknowledgments?|Acknowledgements?|"
               r"References|Bibliography|Appendix)$", re.IGNORECASE),
]

# For detecting the start of the references section
_REFERENCES_HEADER = re.compile(
    r"^(References|Bibliography)\s*$", re.IGNORECASE
)

# Numbered reference entry: [1], [2], etc.
_NUMBERED_REF = re.compile(r"^\[(\d+)\]\s*(.+)")


class PaperReader:
    """Read a scientific paper PDF and split into sections + references."""

    def read(self, source: str) -> dict:
        """Return structured paper data with sections and references.

        source can be:
        - A file path to a PDF
        - "arxiv:XXXX.XXXXX" to download from arXiv
        """
        pdf_path = self._resolve_source(source)
        return self._parse_pdf(pdf_path)

    def _resolve_source(self, source: str) -> str:
        """Download if arxiv: prefix, otherwise return as-is."""
        if source.startswith("arxiv:"):
            arxiv_id = source[6:]
            url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            urllib.request.urlretrieve(url, tmp.name)
            return tmp.name
        return source

    def _parse_pdf(self, pdf_path: str) -> dict:
        import pymupdf

        doc = pymupdf.open(pdf_path)

        # Extract all text by page
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()

        full_text = "\n".join(pages_text)
        lines = full_text.split("\n")

        # Extract title and authors from first page
        title = self._extract_title(lines)
        authors = self._extract_authors(lines)

        # Split into sections
        sections = self._split_sections(lines)

        # Separate references from body sections
        ref_section_text = ""
        body_sections = []
        for section in sections:
            if _REFERENCES_HEADER.match(section["name"].strip()):
                ref_section_text = section["text"]
            else:
                body_sections.append(section)

        # Parse references
        references = self._parse_references(ref_section_text, lines)

        # Build chunks from body sections
        # sections: list[dict] with section metadata (for paper-aware consumers)
        # chunks: list[str] for pipeline compatibility (ingest expects strings)
        sections_out = []
        chunks = []
        for section in body_sections:
            text = section["text"].strip()
            if text and len(text) > 50:
                section_name = section["name"].lower().strip()
                sections_out.append({
                    "section": section_name,
                    "text": text,
                })
                # Prefix chunk with section header for context
                chunks.append(f"[{section_name}]\n{text}")

        return {
            "title": title,
            "type": "paper",
            "metadata": {
                "authors": authors,
            },
            "sections": sections_out,
            "chunks": chunks,
            "references": references,
        }

    def _extract_title(self, lines: list[str]) -> str:
        """Heuristic: title is a capitalized line that isn't boilerplate."""
        boilerplate_words = {"permission", "reproduce", "granted", "license", "copyright",
                             "proceedings", "published", "submitted", "accepted", "journal",
                             "scholarly", "journalistic", "solely", "hereby", "attribution"}

        # Phase 1: find lines that look like titles (short enough, capitalized,
        # no trailing period, not boilerplate)
        for line in lines[:50]:
            stripped = line.strip()
            if not stripped or len(stripped) < 10 or len(stripped) > 200:
                continue
            if "@" in stripped or stripped.endswith("."):
                continue
            # Skip affiliations
            if re.match(r"^(University|Google|Microsoft|Meta|OpenAI|DeepMind)", stripped):
                continue
            # Skip author lines (contain superscript markers, many commas, or † ‡ * symbols)
            if re.search(r"\d[,†‡∗\*]", stripped) or stripped.count(",") >= 4:
                continue
            # Skip lines with boilerplate words
            words_lower = set(stripped.lower().split())
            if words_lower & boilerplate_words:
                continue
            # Title should start with a capital letter and have mostly capitalized words
            words = stripped.split()
            cap_count = sum(1 for w in words if w[0].isupper())
            # Short titles (1-2 words) are fine if they're on the first page and capitalized
            if cap_count >= len(words) * 0.5:
                return stripped

        # Phase 2: fallback — just grab the first non-trivial line
        for line in lines[:30]:
            stripped = line.strip()
            if stripped and len(stripped) >= 15 and not stripped.endswith("."):
                words_lower = set(stripped.lower().split())
                if not (words_lower & boilerplate_words):
                    return stripped

        return "Unknown Paper"

    def _extract_authors(self, lines: list[str]) -> list[str]:
        """Extract author names from the first page header area."""
        authors = []
        # Look for lines between title and abstract that contain names
        in_header = False
        for line in lines[:60]:
            stripped = line.strip()
            if not stripped:
                continue
            # After we see the title-like area, look for author-like lines
            if re.match(r"^Abstract", stripped, re.IGNORECASE):
                break
            # Author lines: contain name-like patterns, possibly with asterisks/daggers
            # Skip emails, affiliations, permission notices
            if "@" in stripped:
                continue
            if re.match(r"^(Provided|Published|Proceedings|Copyright|arXiv)", stripped, re.IGNORECASE):
                continue
            if re.match(r"^(University|Google|Microsoft|Meta|OpenAI|DeepMind)", stripped):
                continue
            # Name-like: 2-4 capitalized words, possibly with symbols
            name_match = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)?(?:\s+[A-Z][a-z]+)+)[∗†‡\*]*$", stripped)
            if name_match:
                name = re.sub(r"[∗†‡\*]+$", "", name_match.group(1)).strip()
                if name and len(name) > 3:
                    authors.append(name)

        return authors

    def _split_sections(self, lines: list[str]) -> list[dict]:
        """Split document into named sections based on header detection."""
        sections = []
        current_name = "preamble"
        current_lines = []

        for line in lines:
            stripped = line.strip()
            is_header = False

            for pattern in _SECTION_PATTERNS:
                m = pattern.match(stripped)
                if m:
                    # Save previous section
                    if current_lines:
                        sections.append({
                            "name": current_name,
                            "text": "\n".join(current_lines),
                        })
                    # Start new section
                    if m.lastindex and m.lastindex >= 2:
                        current_name = m.group(2).strip()
                    else:
                        current_name = stripped
                    current_lines = []
                    is_header = True
                    break

            if not is_header:
                current_lines.append(line)

        # Don't forget the last section
        if current_lines:
            sections.append({
                "name": current_name,
                "text": "\n".join(current_lines),
            })

        return sections

    def _parse_references(self, ref_text: str, all_lines: list[str]) -> list[dict]:
        """Parse references in numbered [1] or APA (author-first) format."""
        # If we didn't find a clean references section, try to find it in all_lines
        if not ref_text:
            ref_text = self._find_references_in_lines(all_lines)

        if not ref_text:
            return []

        # Try numbered format first
        references = self._parse_numbered_refs(ref_text)
        if references:
            return references

        # Fall back to APA/author-first format
        return self._parse_apa_refs(ref_text)

    def _parse_numbered_refs(self, ref_text: str) -> list[dict]:
        """Parse [1]-style numbered references."""
        entries = []
        current_num = None
        current_text = ""

        for line in ref_text.split("\n"):
            stripped = line.strip()
            m = _NUMBERED_REF.match(stripped)
            if m:
                if current_num is not None:
                    entries.append((current_num, current_text.strip()))
                current_num = int(m.group(1))
                current_text = m.group(2)
            elif current_num is not None and stripped:
                if re.match(r"^\d+$", stripped):
                    continue
                current_text += " " + stripped

        if current_num is not None:
            entries.append((current_num, current_text.strip()))

        references = []
        for num, text in entries:
            ref = self._parse_single_reference(num, text)
            references.append(ref)
        return references

    def _parse_apa_refs(self, ref_text: str) -> list[dict]:
        """Parse APA/author-first references (no [N] numbering).

        Strategy: entries are separated by blank lines, or each entry starts
        with a line matching 'AuthorLastName, FirstInitial.' pattern.
        """
        # Always use the year-boundary splitter — it handles both blank-line-separated
        # and contiguous formats correctly.
        blocks = self._split_contiguous_apa(ref_text)

        references = []
        for i, block in enumerate(blocks):
            text = " ".join(block.split())  # normalize whitespace
            if len(text) < 20:
                continue
            # Skip page numbers, section headers
            if re.match(r"^\d+$", text.strip()):
                continue
            if re.match(r"^(Appendix|Supplementary|Figure|Table)\b", text):
                break

            ref = self._parse_single_reference(i + 1, text)
            if ref.get("title") and len(ref["title"]) > 5:
                references.append(ref)

        return references

    def _split_contiguous_apa(self, ref_text: str) -> list[str]:
        """Split contiguous APA references where entries aren't separated by blank lines.

        Each entry ends with a year followed by a period (e.g. ', 2024.').
        A new entry starts on the next non-empty line after that.
        """
        lines = ref_text.split("\n")
        blocks = []
        current_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # Blank line — might be entry boundary
                if current_lines:
                    merged = " ".join(current_lines)
                    # Check if we ended an entry (year at end)
                    if re.search(r"(19|20)\d{2}[a-z]?\.\s*$", merged):
                        blocks.append(merged)
                        current_lines = []
                        continue
                continue

            # Skip standalone page numbers
            if re.match(r"^\d+$", stripped):
                continue

            # Check if previous accumulated text ended with year. pattern
            # and this line starts a new author (capital letter)
            if current_lines:
                merged = " ".join(current_lines)
                if (re.search(r"(19|20)\d{2}[a-z]?\.\s*$", merged)
                        and re.match(r"^[A-Z]", stripped)):
                    blocks.append(merged)
                    current_lines = [stripped]
                    continue

            current_lines.append(stripped)

        if current_lines:
            blocks.append(" ".join(current_lines))

        return blocks

    def _find_references_in_lines(self, lines: list[str]) -> str:
        """Fallback: scan all lines for the references section."""
        start = None
        for i, line in enumerate(lines):
            if _REFERENCES_HEADER.match(line.strip()):
                start = i + 1
                break

        if start is None:
            return ""

        # Collect until we hit appendix or end
        ref_lines = []
        for line in lines[start:]:
            stripped = line.strip()
            if re.match(r"^(Appendix|Supplementary)", stripped, re.IGNORECASE):
                break
            ref_lines.append(line)

        return "\n".join(ref_lines)

    def _parse_single_reference(self, num: int, text: str) -> dict:
        """Parse a single reference entry into structured data."""
        authors = []
        title = text  # fallback

        # Find the author/title boundary.
        # Authors end with a period followed by a space and then a word that
        # starts a title (typically 4+ chars, capitalized). We need to skip
        # initials like "V. Le" or "N. Smith" where the period is part of a name.
        # Strategy: find ". " where the next word is 4+ chars or the segment
        # after it is 20+ chars (i.e., it's a title, not a last name).
        boundary = None
        i = 0
        while i < len(text):
            dot_pos = text.find(". ", i)
            if dot_pos == -1:
                break
            after = text[dot_pos + 2:].strip()
            # Check if what follows looks like a title start (long word or long segment)
            first_word = after.split()[0] if after.split() else ""
            # Skip if it looks like a last name after an initial (short, followed by comma/period)
            if len(first_word) <= 3 or (len(first_word) <= 6 and "," in after[:20]):
                i = dot_pos + 2
                continue
            # This looks like the title boundary
            boundary = dot_pos
            break

        if boundary is not None:
            author_text = text[:boundary]
            rest = text[boundary + 2:]
            # Title is the next sentence
            # Find the end of the title (next ". " or end of string)
            title_end = rest.find(". ")
            if title_end != -1:
                title = rest[:title_end]
            else:
                title = rest

            # Parse authors
            author_text = re.sub(r",?\s+and\s+", ", ", author_text)
            raw_authors = [a.strip() for a in author_text.split(", ")]
            for a in raw_authors:
                if a and re.match(r"[A-Z]", a) and len(a) > 2:
                    authors.append(a)

        # Try to extract year
        year = None
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        if year_match:
            year = int(year_match.group())

        # Try to extract arXiv ID
        arxiv_match = re.search(r"arXiv[:\s]+(?:preprint\s+)?(?:arXiv[:\s]+)?(\d{4}\.\d{4,5})", text)
        arxiv_id = arxiv_match.group(1) if arxiv_match else None

        ref = {
            "number": num,
            "title": title.strip().rstrip("."),
            "authors": authors,
            "raw": text,
        }
        if year:
            ref["year"] = year
        if arxiv_id:
            ref["arxiv_id"] = arxiv_id

        return ref
