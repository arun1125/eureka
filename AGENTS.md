# Eureka — Agent Instructions

You are operating a molecular knowledge system. Eureka turns raw sources into atomic ideas, links them by semantic similarity, and discovers synthesized insights using embedding geometry.

## Quick Start

```bash
# Set brain dir once (or pass --brain-dir to every command)
export EUREKA_BRAIN=/path/to/brain

eureka init ~/brain                     # One-time setup
eureka ingest <source> --brain-dir DIR  # Add knowledge
eureka status                           # Check brain health
eureka discover                         # Find & write new molecules
eureka ask "question"                   # Query the brain
eureka review <slug> yes|no             # Accept or reject insights
eureka serve                            # Visual dashboard
```

## Brain Directory

Every command needs a brain directory. Three ways to specify it (checked in order):

1. `--brain-dir /path/to/brain` flag
2. `EUREKA_BRAIN` environment variable
3. Positional argument (for `discover`, `status`, `serve`)

## Output Format

Every command returns JSON on stdout:

```json
{"ok": true, "command": "...", "data": {...}, "errors": [], "warnings": []}
```

Progress messages go to stderr. Parse stdout only.

## Commands

### eureka init \<dir\>

Create a new brain directory with empty database.

### eureka ingest \<source\> --brain-dir \<dir\> [--paper]

Add a source to the brain. Handles: file paths, URLs, YouTube links, directories (Obsidian/Notion), `arxiv:XXXX.XXXXX` prefixes.

- `--paper` flag forces PaperReader for any PDF (sections + references + citation graph)
- Idempotent: re-ingesting the same source is a no-op

After ingest, embeddings and links are recalculated automatically.

### eureka discover [--count N]

Run all 8 discovery methods (triangles, v-structures, walks, bridges, antipodal, voids, cluster-boundary, residuals). Scores candidates, writes top N molecules (default 10) using LLM.

Molecules are written to `<brain_dir>/molecules/` as markdown files and stored in the `molecules` DB table.

### eureka ask "question"

Graph-aware retrieval. Returns: nearest atoms, graph neighbors (1-hop), relevant molecules, tensions.

### eureka review \<slug\> yes|no

Accept or reject a pending molecule.

### eureka status

Atom/molecule/source counts, embedding model, health info.

### eureka dump "text"

Process a raw text dump — extract atoms via LLM and add to brain.

### eureka profile [--answers "text"]

Without `--answers`: returns onboarding questions. With `--answers`: processes answers into profile atoms.

### eureka reflect

Generate a reflection based on the brain's current state.

### eureka serve [--port N]

Visual dashboard on localhost (default 8765). For humans, not agents.

## Embeddings

Default: **Gemini Embedding 001** (3072-dim, #1 MTEB). Requires `GEMINI_API_KEY` in env or in `tech/secrets/.env`.

Fallback: FastEmbed bge-small-en-v1.5 (384-dim) if no Gemini key.

### Re-embedding (e.g. after model upgrade)

No CLI command yet. Use Python directly:

```python
from eureka.core.db import open_db
from eureka.core.embeddings import ensure_embeddings
from eureka.core.linker import link_all
from pathlib import Path

brain_dir = Path("/path/to/brain")
conn = open_db(brain_dir)

# Re-embed all atoms with current model (force=True clears old vectors)
ensure_embeddings(conn, brain_dir, force=True)

# Recompute edges from new embeddings
edges = link_all(conn)
print(f"Created {edges} edges")

conn.close()
```

## Database

SQLite database at `<brain_dir>/brain.db`. Source of truth.

### Key tables

**Note:** Some brains use `notes` table, others use `atoms`. The code auto-detects via `eureka.core.db.atom_table(conn)`.

- `notes` or `atoms` — atomic ideas (slug PK, body, tags, source)
- `molecules` — synthesized insights (slug PK, method, score 0-100, review_status, eli5, body)
- `molecule_atoms` — which atoms form which molecules
- `sources` — ingested sources (title, type, url, atom_count)
- `edges` — similarity links between notes (source, target, similarity)
- `embeddings` — cached vectors (slug, model, vector BLOB, updated)
- `discovery_runs` — log of discover invocations

### Common queries

```sql
-- Pending molecules
SELECT slug, method, score, eli5 FROM molecules WHERE review_status = 'pending' ORDER BY score DESC;

-- Check embedding model and count
SELECT model, count(*) FROM embeddings GROUP BY model;

-- Check vector dimensions
SELECT length(vector)/4 AS dims FROM embeddings LIMIT 1;

-- Top molecules
SELECT slug, score, eli5, method FROM molecules WHERE review_status = 'accepted' ORDER BY score DESC LIMIT 10;

-- Unexploited atoms (not in any molecule)
SELECT n.slug FROM notes n WHERE n.slug NOT IN (SELECT atom_slug FROM molecule_atoms);
```

## Error Handling

All errors include a suggestion field:

```json
{"ok": false, "errors": [{"message": "source not found", "suggestion": "Check the file path."}]}
```

Read the suggestion before retrying.
