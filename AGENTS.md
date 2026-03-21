# Eureka — Agent Instructions

You are operating a molecular knowledge system. Eureka turns raw sources into atomic ideas, links them by semantic similarity, and discovers synthesized insights using embedding geometry.

## Quick Start

```
eureka init ~/brain                     # One-time setup
eureka ingest <source> --brain-dir DIR  # Add knowledge
eureka status DIR                       # Check brain health
eureka discover DIR                     # Find new insights
eureka ask "question" --brain-dir DIR   # Query the brain
eureka review <slug> yes|no --brain-dir DIR  # Accept or reject insights
eureka serve DIR                        # Visual dashboard for the user
```

## Output Format

Every command returns JSON on stdout:

```json
{"ok": true, "command": "...", "data": {...}, "errors": [], "warnings": []}
```

Progress messages go to stderr. Parse stdout only.

## Exit Codes

```
0 = success
1 = failure (see errors array for details + suggestions)
2 = usage error (bad arguments)
3 = not found (brain, slug, or source)
5 = conflict (already exists, already reviewed)
```

## Commands

### eureka ingest \<source\> --brain-dir \<dir\>

Add a source to the brain. Handles: file paths, URLs, YouTube links, directories (Obsidian/Notion).

Returns: atoms created, edges formed, top molecule candidate with ELI5.

Idempotent: re-ingesting the same source is a no-op (exit 0).

### eureka discover \<dir\>

Run discovery across the entire brain. Scores candidates, auto-keeps top scorer, returns it with ELI5. Remaining candidates go to pending review.

### eureka ask "question" --brain-dir \<dir\>

Graph-aware retrieval. Returns: nearest atoms, graph neighbors (1-hop), relevant molecules, tensions (V-structures near the question).

You synthesize the answer from these structured results.

### eureka review \<slug\> yes|no --brain-dir \<dir\>

Accept or reject a pending molecule. Accepted molecules persist. Rejected molecules are deleted and suppress similar future candidates.

### eureka status \<dir\>

Returns: atom/molecule/source counts, health score, pending review count.

### eureka serve \<dir\> [--port N]

Starts the visual dashboard on localhost (default port 8765). The user explores in their browser. You don't need to interact with the dashboard — it's for humans.

## Database

The brain's SQLite database (brain.db) is the source of truth. You can query it directly for advanced operations:

```
sqlite3 ~/brain/brain.db "SELECT slug, score, eli5 FROM molecules WHERE review_status='accepted' ORDER BY score DESC LIMIT 5"
```

### Key tables

- `atoms` — all atomic ideas (slug PK, body, source_id, body_hash)
- `molecules` — synthesized insights (slug PK, method, score 0-100, review_status, eli5, body)
- `molecule_atoms` — which atoms form which molecules
- `sources` — ingested sources (title, type, url, atom_count)
- `edges` — links between notes with cosine similarity
- `embeddings` — cached 384-dim vectors
- `tags` / `note_tags` — non-exclusive topic labels
- `reviews` — audit log of accept/reject decisions
- `discovery_runs` — log of every discover invocation

### Common queries

```sql
-- Pending molecules
SELECT slug, method, score, eli5 FROM molecules WHERE review_status = 'pending' ORDER BY score DESC;

-- Atoms from a source
SELECT a.slug, a.body FROM atoms a JOIN sources s ON a.source_id = s.id WHERE s.title LIKE '%keyword%';

-- Top molecules
SELECT slug, score, eli5, method FROM molecules WHERE review_status = 'accepted' ORDER BY score DESC LIMIT 10;

-- Unexploited atoms (not in any molecule)
SELECT a.slug FROM atoms a WHERE a.slug NOT IN (SELECT atom_slug FROM molecule_atoms);
```

## Error Handling

All errors include a suggestion field:

```json
{"ok": false, "errors": [{"message": "source not found", "suggestion": "Check the file path. Supported: .pdf, .md, .txt, URLs, YouTube links"}]}
```

Read the suggestion before retrying.
