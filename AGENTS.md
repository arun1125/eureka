# Eureka — Agent Instructions

You are operating a molecular knowledge system. Eureka turns raw sources into atomic ideas, links them by semantic similarity, and discovers synthesized insights using embedding geometry.

## First-Time Setup (for agents)

When setting up Eureka for a new user, run the setup flow **before** any other command.

### Step 1: Get setup instructions (machine-readable)

```bash
eureka setup-instructions
```

This returns a JSON object describing every provider option with cost, requirements, and the exact CLI command to run. Use this to present choices to the user.

### Step 2: Ask the user

The user needs to choose one LLM backend:

| Option | What it uses | Needs API key? | Cost |
|--------|-------------|----------------|------|
| `claude-cli` | Claude Code / Max / Pro subscription via `claude -p` | No | Included in subscription |
| `claude` | Anthropic API direct | Yes (`ANTHROPIC_API_KEY`) | Pay-per-token |
| `openai` | OpenAI API (GPT-4o, etc.) | Yes (`OPENAI_API_KEY`) | Pay-per-token |
| `gemini` | Gemini CLI on PATH | No | Free tier available |
| `ollama` | Local models via Ollama | No | Free (local hardware) |
| `openrouter` | 200+ models via openrouter.ai | Yes (`OPENROUTER_API_KEY`) | Pay-per-token |
| `together` | Together AI | Yes (`TOGETHER_API_KEY`) | Pay-per-token |
| `groq` | Groq (ultra-fast) | Yes (`GROQ_API_KEY`) | Free tier + pay |
| `deepseek` | DeepSeek | Yes (`DEEPSEEK_API_KEY`) | Pay-per-token (cheap) |
| `openai-compatible` | Any OpenAI-compatible endpoint | Varies | Varies |

Ask: **"Do you want Eureka to use your Claude Code subscription (no extra cost), or API tokens from a provider like OpenAI, Anthropic, Groq, etc.?"**

### Step 3: Configure (non-interactive, for agents)

```bash
# Subscription user (Claude Max/Pro — no key needed)
eureka setup --brain-dir ~/brain --provider claude-cli --model sonnet

# API user (Anthropic)
eureka setup --brain-dir ~/brain --provider claude --api-key sk-ant-xxx

# OpenAI
eureka setup --brain-dir ~/brain --provider openai --model gpt-4o-mini --api-key sk-xxx

# Gemini CLI
eureka setup --brain-dir ~/brain --provider gemini

# Ollama (local, no key)
eureka setup --brain-dir ~/brain --provider ollama --model llama3.1

# Groq
eureka setup --brain-dir ~/brain --provider groq --api-key gsk_xxx

# OpenRouter
eureka setup --brain-dir ~/brain --provider openrouter --model anthropic/claude-haiku --api-key sk-or-xxx

# Any OpenAI-compatible endpoint
eureka setup --brain-dir ~/brain --provider openai-compatible --base-url https://api.example.com/v1 --model model-name --api-key xxx
```

This writes `brain.json` and optionally `.env`, then tests the connection.

### Step 3 (alt): Interactive setup (for humans)

```bash
eureka setup --brain-dir ~/brain
```

Walks through provider → model → API key → connection test interactively.

### Embedding note

Separately from LLM, Eureka uses **Gemini Embedding 001** (3072-dim) for vectors. Set `GEMINI_API_KEY` for best quality. Falls back to local FastEmbed (384-dim) if no key. This is independent of the LLM provider choice.

---

## Quick Start

```bash
# Set brain dir once (or pass --brain-dir to every command)
export EUREKA_BRAIN=/path/to/brain

eureka init ~/brain                     # One-time setup
eureka setup --brain-dir ~/brain        # Configure LLM provider
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

Exit codes: 0=success, 1=failure, 2=usage error, 3=not found, 5=conflict.

## Environment

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API key (preferred) |
| `CLAUDE_MODEL` | Override model. Default: `claude-haiku-4-5-20251001` |
| `GEMINI_API_KEY` | Gemini Embedding 001 (3072-dim embeddings) |
| `MOONSHOT_API_KEY` | Kimi K2.5 fallback |
| _(none)_ | Falls back to `gemini` CLI on PATH |

LLM needed: `discover`, `ask`, `dump`, `profile --answers`.
No LLM: `init`, `ingest`, `status`, `serve`, `reflect`, `review`.

## Commands

### eureka init \<dir\>

Create a new brain directory with empty database.

### eureka ingest \<source\> --brain-dir \<dir\> [--paper]

Add a source to the brain. Handles: file paths, URLs, YouTube links, directories (Obsidian/Notion), `arxiv:XXXX.XXXXX` prefixes.

- `--paper` flag forces PaperReader for any PDF (sections + references + citation graph)
- Idempotent: re-ingesting the same source is a no-op
- After ingest, embeddings and links are recalculated automatically

**Supported formats:**

| Format | Reader | Notes |
|--------|--------|-------|
| PDF | pymupdf | Best for books. Page-by-page text extraction. |
| PDF (scientific) | PaperReader (`--paper`) | Sections + references + citation graph |
| EPUB | zipfile + HTML parsing | Handles most e-books. |
| TXT | Plain read | Transcripts, notes, articles. |
| `arxiv:XXXX.XXXXX` | PaperReader | Downloads PDF from arXiv automatically |
| Directory | Obsidian/Notion parser | Imports `.md` files from vault/export |

**Pipeline steps:** Read → Chunk → Extract atoms (LLM) → Write markdown → Index in DB → Embed → Link

**YouTube workaround** (no built-in reader):

```bash
yt-dlp --write-auto-sub --sub-lang en --skip-download -o "%(title)s" "URL"
sed '/^$/d; /^[0-9]/d; /-->/d' "Title.en.vtt" | sort -u > transcript.txt
eureka ingest transcript.txt --brain-dir ../brain
```

**Quality tips:**
- Back up `brain.db` before ingesting
- One source at a time — review before next ingest
- Use Sonnet (`CLAUDE_MODEL=claude-sonnet-4-6-20250514`) for dense philosophical texts
- Large PDFs (500+ pages): budget 5-10 min, check LLM costs

### eureka discover [--count N]

Run all 8 discovery methods, score candidates, write top N molecules (default 10) using LLM.

Molecules are written to `<brain_dir>/molecules/` as markdown files and stored in the `molecules` DB table.

**8 Discovery Methods:**

| Method | Friendly Name | What it finds |
|--------|--------------|---------------|
| `triangle` | Trio | 3 atoms with moderate pairwise similarity (0.4-0.85) |
| `walk` | Journey | Random walk along edges, sampling evenly spaced atoms |
| `antipodal` | Opposites | Max semantic distance atoms sharing a structural neighbor |
| `cluster-boundary` | Frontier | Atoms at community edges, near another community |
| `bridge` | Bridge | Atoms connecting two disconnected communities |
| `v-structure` | V-Structure | Two distant atoms both close to a hinge atom |
| `void` | Gap | Semantic gaps between clusters — midpoints where no atom exists |
| `residual` | Hidden Gem | Underconnected atoms with few edges relative to potential |

**Best defaults:** Trio = safest. Journey = best for surprising long-range connections. Opposites = most creative tensions. V-Structure = hidden tension via a shared connector.

**Scoring formula:**

```
score = coherence × novelty × emergence^1.5 × source_diversity × size_bonus
```

- **Coherence**: avg pairwise cosine similarity
- **Novelty**: `sqrt(1 - coherence²)` — penalizes too-similar and too-distant
- **Emergence**: ratio of avg atom typicality to centroid typicality (rarer combo = higher)
- **Source diversity**: 1.0 (same) → 1.3 (2 sources) → 1.6 (3) → 2.0 (4+)
- **Size bonus**: 1.0 (3 atoms) → 1.15 (4) → 1.3 (5)

Score >30 decent, >50 strong, >70 exceptional.

**LLM output format:** Title (opinionated claim) + Body (2 paragraphs with `[[wikilinks]]`) + ELI5 (one-liner with concrete metaphor).

Use Haiku for batch (20+). Sonnet for important molecules.

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

Generate a reflection based on the brain's current state — themes, gaps, blind spots. No LLM needed.

### eureka serve [--port N]

Visual dashboard on localhost (default 8765). Tabs: Graph, Search, Molecules, Idea Lab, Review.

## Dashboard HTTP API

Start: `eureka serve ../brain --port 8765`

All endpoints return JSON. Base URL: `http://localhost:8765`

### GET Endpoints

| Endpoint | Returns |
|----------|---------|
| `/api/stats` | Atom/molecule/edge counts, source list with per-source atom counts |
| `/api/graph` | D3-compatible nodes (id, title, community) + links (source, target, weight) |
| `/api/search?q=TEXT&source=ID` | Atoms matching text query, optional source filter |
| `/api/molecules` | All molecules with score, method, atoms, review status |
| `/api/neighbors?atom=SLUG&exclude=S1,S2&limit=6` | Nearest neighbors by embedding similarity |
| `/api/discover/from?atom=SLUG&method=METHOD` | Candidates from a specific atom |
| `/api/atom/SLUG` | Single atom or molecule detail (body, tags, source) |
| `/api/profile` | Profile questions from brain themes |
| `/api/activity` | Recent operations log |
| `/api/reflect` | Structural analysis — patterns, blind spots, gaps |

### POST Endpoints

| Endpoint | Body | Returns |
|----------|------|---------|
| `/api/generate-molecule` | `{"atoms": ["slug1", "slug2", "slug3"]}` | Generated molecule (slug, title, body, score) |
| `/api/review/SLUG` | `{"decision": "yes"\|"no"\|"skip"}` | Confirmation |

### Scripting Example

```bash
ATOM=$(curl -s "localhost:8765/api/search?q=discipline" | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['slug'])")
curl -s "localhost:8765/api/discover/from?atom=$ATOM&method=triangle"
curl -s -X POST localhost:8765/api/generate-molecule \
  -H "Content-Type: application/json" \
  -d '{"atoms":["slug1","slug2","slug3"]}'
```

## Embeddings

Default: **Gemini Embedding 001** (3072-dim, #1 MTEB). Requires `GEMINI_API_KEY` in env.

Fallback: FastEmbed bge-small-en-v1.5 (384-dim) if no Gemini key.

### Re-embedding (after model upgrade or manual edits)

No CLI command yet. Use Python directly:

```python
from eureka.core.db import open_db
from eureka.core.embeddings import ensure_embeddings
from eureka.core.linker import link_all
from pathlib import Path

brain_dir = Path("/path/to/brain")
conn = open_db(brain_dir)
ensure_embeddings(conn, brain_dir, force=True)  # force=True clears old vectors
edges = link_all(conn)
print(f"Created {edges} edges")
conn.close()
```

## Database

SQLite database at `<brain_dir>/brain.db`. Source of truth.

**Note:** Some brains use `notes` table, others use `atoms`. The code auto-detects via `eureka.core.db.atom_table(conn)`.

### Key Tables

- `notes` or `atoms` — atomic ideas (slug PK, body, tags, source)
- `molecules` — synthesized insights (slug PK, method, score 0-100, review_status, eli5, body)
- `molecule_atoms` — which atoms form which molecules
- `sources` — ingested sources (title, type, url, atom_count)
- `edges` — similarity links between notes (source, target, similarity)
- `embeddings` — cached vectors (slug, model, vector BLOB, updated)
- `discovery_runs` — log of discover invocations

### Common Queries

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

## Maintenance

### Backup

```bash
cp brain/brain.db brain/brain.db.bak
```

Always before destructive operations. The DB is source of truth; markdown files are secondary.

### Health Check

```bash
eureka status ../brain
```

Run after every ingest or discover. Check embedding coverage = 100%.

### Reviewing Molecules

**Dashboard** (preferred): `eureka serve ../brain` → Review tab. Keys: `y`=accept, `n`=reject, `s`=skip, arrows to navigate.

**CLI**: `eureka review slug yes --brain-dir ../brain`

### Pruning

No hard-delete command. Workflow:
1. Review as `no` → dashboard hides them
2. Physical removal: `rm brain/molecules/bad-slug.md` + `DELETE FROM molecules WHERE slug = ?`

### Routine Checklist

1. `status` — verify counts
2. `reflect` — check blind spots
3. Review unreviewed molecules
4. Backup before new ingests
5. `discover --count 20` after each ingest

## Error Handling

All errors include a suggestion field:

```json
{"ok": false, "errors": [{"message": "source not found", "suggestion": "Check the file path."}]}
```

Read the suggestion before retrying.

## Typical Workflow

```bash
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=sk-ant-...

eureka init ~/brain
eureka ingest ~/Books/book.pdf --brain-dir ~/brain
eureka ingest arxiv:1706.03762 --brain-dir ~/brain --paper
eureka discover ~/brain --count 20
eureka serve ~/brain                    # review in browser
eureka ask "How do habits form?" --brain-dir ~/brain
eureka status ~/brain
```
