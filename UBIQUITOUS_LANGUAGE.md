# Ubiquitous Language

Every file, variable, docstring, test, and conversation about Eureka uses these terms exactly as defined. If a term isn't here, it doesn't exist in the domain.

---

## Core Domain

| Term | Definition | Not This |
|------|-----------|----------|
| **Atom** | A single concept or technique, written as an opinionated claim. Title is a complete phrase that argues. Body is 2-5 sentences. Could have its own Wikipedia page. | "note", "card", "idea", "zettel" |
| **Molecule** | An insight synthesized from 2+ atoms. Cross-source, non-obvious — says something none of its atoms say alone. | "connection", "synthesis", "link note" |
| **Source** | Any consumed material: book, video, article, podcast, Obsidian vault, Notion export. The raw input to the pipeline. | "document", "file", "reference" |
| **Edge** | A directed link between two notes (atom or molecule), stored with cosine similarity at link time. Wikilinks in markdown are the human-readable form. | "link", "connection", "relationship" |
| **Slug** | Kebab-case identifier derived from the title. Primary key in the DB. Also the `.md` filename (without extension). e.g., `margin-of-safety-applies-engineering-redundancy-to-investing` | "id", "key", "filename" |
| **Tag** | A non-exclusive topic label on an atom or molecule. Lowercase. Emergent, not prescribed. | "category", "folder", "type" |
| **Brain** | The user's entire knowledge system: the directory containing `brain.db`, `atoms/`, `molecules/`, `brain.json`, and `.git/`. One brain per user (v1). | "vault", "database", "repo", "notebook" |
| **ELI5** | A one-sentence plain-language explanation of a molecule. No jargon. A 10-year-old should understand it. | "summary", "abstract", "description" |

## Pipeline

| Term | Definition | Not This |
|------|-----------|----------|
| **Chunk** | A segment of source text, produced by splitting the source for LLM processing. Not stored long-term — intermediate only. | "section", "paragraph", "block" |
| **Extraction** | The LLM step that turns chunks into atoms. Uses the extraction prompt. | "parsing", "import", "ingestion" (ingestion is the whole pipeline) |
| **Ingest** | The full pipeline triggered by `eureka ingest`: chunk → extract → index → embed → link → discover → report. One-shot. | "import", "add" (too vague) |
| **Embed** | Convert text to a dense vector (384-dim float32 array). Cached in `embeddings` table. Default: fastembed BAAI/bge-small-en-v1.5. | "encode", "vectorize" |
| **Link** | Compute and store edges between a note and its nearest neighbors by embedding similarity. Top-5 per note. | "connect", "relate" |
| **Discover** | Run geometric/topological methods across the brain to find molecule candidates. Scores them. Surfaces the best. | "generate", "create", "synthesize" |
| **Score** | A 0-100 number representing percentage of theoretical maximum. Computed by the scoring function (coherence × novelty × emergence). | "rank", "rating" |
| **Review** | A binary (yes/no) human decision on a pending molecule. Accepted → persists. Rejected → deleted + added to kill list. | "approve", "rate", "evaluate" |

## Discovery Methods

| Term | Definition |
|------|-----------|
| **Triangle** | 3 atoms from 3 different sources, all pairwise similarity 0.65-0.78. Finds agreement across sources. |
| **V-structure** | A and B both relate to bridge C but disagree with each other (A↔C > 0.60, B↔C > 0.60, A↔B < 0.48). Finds tension. Produces highest-scoring molecules. |
| **Bridge** | An atom connecting two otherwise disconnected communities. |
| **Walk** | Random walk on the graph to find distant but reachable combinations. |
| **Antipodal** | Atoms at maximum semantic distance that share a structural path. |
| **Analogy** | Pairs where A:B :: C:D in embedding space. |
| **Centroid** | The geometric center of a community — atoms nearest to it form a molecule. |
| **Interpolation** | Points along the embedding path between two atoms — what's in the semantic gap? |
| **Cluster-boundary** | Atoms at the edge of their community, near another community. |

## Scoring Signals

| Term | Definition |
|------|-----------|
| **Coherence** | Average pairwise cosine similarity of a molecule's constituent atoms. Do they relate? |
| **Novelty** | `sqrt(1 - coherence²)`. Does the combination say something new? Higher when atoms aren't too similar. |
| **Emergence** | Atom typicality / molecule typicality. Is this combination rare relative to random pairings? |
| **IT Score** | Coherence × Novelty × Emergence, normalized to 0-100. The molecule's overall quality signal. |
| **Kill list** | Rejected molecule patterns. Suppresses similar future candidates in discovery. |

## Architecture

| Term | Definition | Not This |
|------|-----------|----------|
| **Component** | A swappable pipeline step with a defined input/output contract. e.g., scoring function, extraction prompt, embedding model. | "plugin" (reserved for user-defined components) |
| **Plugin** | A user-defined component living in `~/brain/plugins/`. Overrides a default component. | "extension", "addon" |
| **Envelope** | The JSON wrapper for all CLI output: `{"ok": bool, "command": str, "data": {}, "errors": [], "warnings": []}` | "response", "result" |
| **Discovery run** | A single invocation of `eureka discover`. Logged in `discovery_runs` table with method, params, and candidate counts. | "generation", "batch" |
| **brain.json** | Per-brain configuration file. Specifies which components to use, thresholds, active discovery methods. | "config.json" (that's the global config) |
| **Global config** | `~/.config/eureka/config.json`. Stores `brain_dir` and LLM credentials. | "brain.json" (that's per-brain) |

## Database

| Term | Definition |
|------|-----------|
| **Source of truth** | SQLite (`brain.db`) holds all metadata, scores, relationships, status. Markdown holds content only. |
| **body_hash** | SHA256 of an atom's body text. Used for change detection when syncing from edited .md files. |
| **review_status** | One of: `pending`, `accepted`, `rejected`. Lives on the molecule row. |
| **molecule_atoms** | Junction table mapping molecules to their constituent atoms. |
| **note_tags** | Junction table mapping any slug (atom or molecule) to tags. |
| **notes_fts** | FTS5 virtual table for full-text search across all slugs, bodies, and tags. |

## Thought Partner (v3)

| Term | Definition | Not This |
|------|-----------|----------|
| **Dump** | Raw text the user brain-dumps — typed, dictated, voice-transcribed. A source with `type = 'dump'`. The extraction prompt is personal, not academic. | "note", "journal entry", "input" |
| **Profile** | First-class atoms tagged `profile` representing the user's goals, patterns, values, and struggles. Also stored in the `profile` table as key-value pairs with confidence scores. | "settings", "preferences", "metadata" |
| **Profile Atom** | An atom extracted from profile answers or inferred from behavior. Tagged `profile`. Participates in linking and discovery like any other atom. | "config", "user setting" |
| **Pushback** | Structured challenge returned by Eureka when the brain disagrees with a query or dump. Types: contradiction, pattern, gap, drift. Always JSON, never prose. | "criticism", "error", "warning" |
| **Contradiction** | Two atoms in the same topical neighborhood whose claims point in opposite directions. Detected by high topical similarity + low directional agreement. A generalization of V-structures. | "conflict", "inconsistency" |
| **Pattern** | A theme the user keeps circling back to — same topic in 3+ dumps over 2+ weeks. Surfaced as pushback. | "trend", "habit", "recurring topic" |
| **Goal-Reality Gap** | When profile goals don't match recent activity. User says they want X but dumps/ingests are all about Y. | "misalignment", "drift" |
| **Reflection** | A brain-wide self-assessment: active topics, recurring patterns, blind spots, goal alignment, molecules to revisit. Output of `eureka reflect`. | "summary", "report", "status" |
| **Blind Spot** | Two topic clusters with high internal connectivity but few cross-links. The gap between them may contain undiscovered insights. | "missing topic", "gap" |
| **Reframe** | A V-structure near the query, formatted as an alternative perspective. "What if the real question isn't A vs B, but how C makes them both true?" | "suggestion", "tip" |
| **Action Suggestion** | A concrete next step derived from goals + brain gaps. "Your brain has nothing on X — consider ingesting a source." | "recommendation", "advice" |
| **Activity Log** | The `activity` table tracking every dump, question, review, and ingest with timestamps. Used for pattern detection, goal-reality gap, and recurring theme analysis. | "history", "audit log" |

## Conventions

- **Slugs** are always kebab-case, derived from the title.
- **Timestamps** are ISO 8601 strings in the DB (`created_at`, `updated_at`, `ingested_at`, `reviewed_at`). Exception: `embeddings.updated` is a Unix float (for mtime comparison).
- **Scores** are always 0-100 (percentage of theoretical max).
- **Tags** are always lowercase.
- **The tool computes. The agent thinks. The human decides.** — Eureka never makes subjective decisions. It surfaces data; the agent interprets; the human judges.
- **Pushback is structured, not generated.** Eureka returns evidence and challenge type. The agent decides tone and delivery.
- **Profile is atoms, not metadata.** Profile entries participate in linking, discovery, and scoring like everything else.
