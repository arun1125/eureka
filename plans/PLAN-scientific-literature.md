# Plan: Scientific Literature Graph

**Goal:** Take a scientific paper, extract its references, build a citation graph, and use Eureka's discovery engine to generate new ideas from the structure.

---

## The Idea

A scientific paper cites 30–80 other papers. Each of those cites 30–80 more. That's a graph — and Eureka already knows how to find interesting things in graphs (voids, missing triangles, cross-community bridges). The hypothesis: if we build atoms from the *claims* in each paper and link them via citation structure, Eureka's discovery methods will surface non-obvious connections that could point to genuinely new research directions.

This is different from a literature review tool. A literature review summarizes what exists. This finds what *doesn't* exist — the gaps, the missing triangles, the unexplored combinations.

---

## Architecture

### What exists (no changes needed)
- Embedding engine (FastEmbed, 384-dim)
- Linker (cosine similarity top-N with threshold)
- Discovery engine (8 methods: triangle, v-structure, walk, bridge, antipodal, void, cluster-boundary, residual)
- Scorer (coherence × novelty × emergence)
- Dashboard (serve command)
- Review pipeline (accept/reject molecules)

### What needs building

#### 1. Paper Reader (`readers/paper.py`)

**Input:** PDF file path, arXiv URL, or DOI
**Output:** Structured chunks with metadata

```python
class PaperReader(BaseReader):
    def read(self, source: str) -> dict:
        return {
            "title": "...",
            "type": "paper",
            "metadata": {
                "authors": [...],
                "year": 2024,
                "doi": "10.1234/...",
                "journal": "Nature",
                "abstract": "...",
            },
            "chunks": [
                {"section": "abstract", "text": "..."},
                {"section": "introduction", "text": "..."},
                {"section": "methods", "text": "..."},
                {"section": "results", "text": "..."},
                {"section": "discussion", "text": "..."},
            ],
            "references": [
                {"title": "...", "authors": [...], "year": 2020, "doi": "..."},
                ...
            ]
        }
```

**Approach:**
- Use PyMuPDF (already a dependency) for PDF text extraction
- Section detection: regex for common headers (Abstract, Introduction, Methods, Results, Discussion, Conclusion, References)
- Reference parsing: detect the References/Bibliography section, parse entries. Two strategies:
  - Regex-based for common citation formats (numbered `[1]`, APA, etc.)
  - LLM fallback for messy formats (agent sends the references section to LLM for structured extraction)
- arXiv support: if input is `arxiv:2301.12345` or an arXiv URL, download PDF first via `https://arxiv.org/pdf/{id}.pdf`

**Open question:** Do we also need to *fetch* the referenced papers? Or just extract their titles/DOIs and create stub atoms?

#### 2. Reference Graph Builder (`core/citation_graph.py`)

Build the citation graph from parsed references.

```python
def build_citation_graph(conn, paper_source_id: int) -> dict:
    """
    For a paper and its references:
    1. Create stub atoms for each referenced paper (title + abstract if available)
    2. Create citation edges (paper → reference)
    3. If multiple papers share references, create co-citation edges
    4. Return graph stats
    """
```

**Two modes:**
- **Shallow (default):** One paper → its references. Atoms from the paper's claims, stub atoms for references (title only). Citation edges connect them.
- **Deep:** Recursively fetch referenced papers (via arXiv, Semantic Scholar API, or DOI resolution), extract their claims too. Builds a multi-hop citation graph. More expensive but richer.

**Co-citation linking:** If paper A and paper B both cite paper C, that's a signal — A and B are related through C even if they don't cite each other. This is exactly a missing triangle.

#### 3. Semantic Scholar Integration (optional, `core/semantic_scholar.py`)

Free API, no auth required for basic lookups:
- `GET https://api.semanticscholar.org/graph/v1/paper/{doi}` — paper metadata
- `GET .../paper/{doi}/references` — outgoing citations
- `GET .../paper/{doi}/citations` — incoming citations (who cites this paper)
- Fields: `title, abstract, year, authors, citationCount, influentialCitationCount, tldr`

Rate limit: 100 requests/5 minutes (free tier). Enough for a single paper's reference tree.

This lets us go from "paper has 40 references" to "we have abstracts and metadata for all 40 referenced papers" without downloading 40 PDFs.

#### 4. Paper-specific Extraction Prompt

Different from book extraction. Papers have:
- **Findings** (from results) — "X causes Y under condition Z"
- **Methods** (from methods) — "We used technique T to measure M"
- **Hypotheses** (from abstract/intro) — "We hypothesize that..."
- **Limitations** (from discussion) — "Our study does not account for..."
- **Open questions** (from discussion/conclusion) — "Future work should explore..."

Each becomes an atom with appropriate tags (finding, method, hypothesis, limitation, open-question).

#### 5. New Discovery Method: Co-citation Void (`discovery.py` extension)

Papers that cite the same references but don't cite each other are semantically related but disconnected in the literature. This is a void in citation space.

```
Paper A cites [R1, R2, R3]
Paper B cites [R2, R3, R4]
Overlap: R2, R3
But A and B don't cite each other
→ Co-citation void: what would a paper combining A's and B's findings look like?
```

This maps directly to the existing void detection (midpoint in embedding space) but uses citation structure instead of pure semantic similarity.

---

## Slices (build order)

### Slice 1: Paper Reader + Basic Ingest
- `PaperReader` class in `readers/paper.py`
- Section detection (abstract, methods, results, discussion, references)
- Reference extraction (regex-based, numbered format)
- `eureka ingest paper.pdf` works end-to-end
- Tests: parse a real paper, verify sections detected, verify references extracted
- **No new commands** — existing `ingest` handles it via reader detection

### Slice 2: Reference Stubs + Citation Edges
- Create stub atoms for each reference (title as atom, no body)
- Citation edges in edges table (source paper → references)
- `eureka status` shows citation edge count
- Tests: ingest paper, verify stub atoms created, verify edges exist

### Slice 3: Semantic Scholar Enrichment
- Fetch abstract + metadata for each reference via Semantic Scholar API
- Enrich stub atoms with abstract text
- Re-embed enriched atoms
- Rate limiting (100/5min)
- Tests: mock API responses, verify enrichment

### Slice 4: Co-citation Discovery
- Co-citation edge detection (papers sharing ≥2 references)
- Add to existing discovery pipeline
- Tests: synthetic citation graph, verify co-citation voids found

### Slice 5: Deep Mode (recursive fetch)
- Follow references one level deep
- Fetch those papers' references too
- Build 2-hop citation graph
- Rate limiting and dedup (don't re-fetch known papers)
- Tests: verify dedup, verify depth limit

### Slice 6: Paper-specific Extraction Prompt
- Separate prompt for paper atoms (findings, methods, hypotheses, limitations, open questions)
- Tag atoms by type
- Tests: verify atom types extracted correctly

---

## First Test Case

Pick a paper you're interested in. Ideally one with:
- 30–50 references (enough to build a graph, not so many it's unwieldy)
- Cross-disciplinary citations (so community detection finds interesting clusters)
- Available on arXiv (free PDF + metadata)

Run it through the pipeline:
1. `eureka ingest arxiv:XXXX.XXXXX` — extract atoms + references
2. `eureka discover` — run all 8 methods on the citation graph
3. See if the generated molecules point to genuinely interesting research directions

---

## Risks

1. **Reference parsing is fragile.** Every paper formats references differently. The regex approach will fail on ~30% of papers. LLM fallback handles this but adds cost/latency.
2. **Stub atoms are thin.** A reference title alone doesn't embed well. Semantic Scholar enrichment (Slice 3) is critical for discovery to work.
3. **Scale.** Deep mode (Slice 5) on a paper with 50 references, each with 50 references = 2,500 papers. Need to be aggressive about dedup and depth limits.
4. **Quality of paper atoms.** Scientific claims are nuanced — "X increases Y by 12% in mice under condition Z" is a very different atom than "the brain is an anticipation machine." The extraction prompt needs to handle this precision without losing generality.
