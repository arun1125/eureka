# Eureka — Agent Instructions

You are operating a molecular knowledge system. Eureka turns raw sources into atomic ideas, links them by semantic similarity, and discovers synthesized insights using embedding geometry.

## Agent Onboarding Flow

When an agent first encounters eureka, follow this exact sequence. Each step is designed to be copy-pasteable and produces JSON output for the agent to parse.

### Step 0: Install

```bash
pip install git+https://github.com/arun1125/eureka.git
```

Verify: `eureka --version` should print the version number.

### Step 1: Initialize a brain

```bash
eureka init ~/brain
```

This creates the directory structure and empty `brain.db`. Pick a location the user wants — `~/brain`, `~/second-brain`, or inside their project.

### Step 2: Get Gemini API key for embeddings

Eureka uses **Gemini Embedding 001** (3072-dim) for all vector operations. This is separate from the LLM provider and is required.

Ask the user: **"I need a Gemini API key for embeddings. You can get one free at https://aistudio.google.com/apikey. Do you have one?"**

Write it to the brain's `.env` file:
```bash
echo 'GEMINI_API_KEY=AIza...' > ~/brain/.env
```

### Step 3: Choose an LLM provider

Call `eureka setup-instructions` to get the full provider list as JSON, then present the user with choices:

```bash
eureka setup-instructions
```

The simplest question to ask: **"Do you want eureka to use your Claude Code subscription (no extra cost), or a separate API key?"**

| Provider | `--provider` | Needs key? | Cost | Best for |
|----------|-------------|------------|------|----------|
| Claude Code subscription | `claude-cli` | No | Included | Claude Max/Pro users |
| Ollama | `ollama` | No | Free | Privacy-first, local models |
| Gemini CLI | `gemini` | No | Free tier | Already have `gemini` CLI |
| Claude API | `claude` | Yes | Pay-per-token | High quality, separate billing |
| OpenAI | `openai` | Yes | Pay-per-token | GPT-4o users |
| Groq | `groq` | Yes | Free tier | Fast inference |
| DeepSeek | `deepseek` | Yes | Cheap | Budget-conscious |
| OpenRouter | `openrouter` | Yes | Varies | Model variety |

### Step 4: Configure

```bash
# Claude Code subscriber (most common — zero config)
eureka setup --brain-dir ~/brain --provider claude-cli --model sonnet

# Ollama (free, local)
eureka setup --brain-dir ~/brain --provider ollama --model llama3.1

# OpenAI API
eureka setup --brain-dir ~/brain --provider openai --model gpt-4o-mini --api-key sk-xxx

# Any OpenAI-compatible endpoint
eureka setup --brain-dir ~/brain --provider openai-compatible \
  --base-url https://api.example.com/v1 --model model-name --api-key xxx
```

This writes `brain.json` and tests the connection. If the test fails, the error tells you what's wrong.

### Step 5: First ingest

```bash
eureka ingest ~/Downloads/some-book.pdf --brain-dir ~/brain
```

After ingest, run `eureka status --brain-dir ~/brain` to verify atoms were created and embeddings are at 100%.

### Step 6: Verify it works

```bash
# Ask a question — should return nearest atoms, graph neighbors, tensions
eureka ask "what is the main idea?" --brain-dir ~/brain

# Check brain stats
eureka status --brain-dir ~/brain
```

If both return valid JSON with `"ok": true`, setup is complete. Set `EUREKA_BRAIN=~/brain` in the user's shell profile for convenience.

### Step 7 (optional): Profile

```bash
# Get onboarding questions
eureka profile --brain-dir ~/brain

# Submit answers — improves search relevance
eureka profile --brain-dir ~/brain --answers '{"goals": "build a YouTube channel", "interests": "AI, philosophy"}'
```

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
eureka decide "question"                # Structured decision support
eureka resolve <slug> --outcome "..."   # Record decision outcomes
eureka patterns                         # Analyze decision quality
eureka lint                             # Brain health checks
eureka lint --deep                      # LLM-judged contradictions/gaps
eureka trends                           # Focus shifts over time
eureka revisit                          # Old atoms newly relevant
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

LLM needed: `discover`, `ask`, `dump`, `decide`, `lint --deep`, `profile --answers`.
No LLM: `init`, `ingest`, `status`, `serve`, `reflect`, `review`, `lint`, `trends`, `revisit`, `resolve`, `patterns`.

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

### eureka decide "question" [--context "extra info"] [--no-file]

Structured decision support. Retrieves relevant atoms via graph-aware search, reads their bodies, sends to LLM for structured analysis. Returns:
- `for_arguments` — reasons in favor
- `against_arguments` — reasons against
- `tensions` — key tradeoffs in your knowledge
- `unknowns` — what the brain can't answer
- `recommendation` — weighted by profile goals
- `atoms_consulted` — which atoms informed the decision

By default files the decision as a molecule and logs it for outcome tracking. Use `--no-file` to skip.

### eureka resolve \<slug\> --outcome "what happened"

Record the outcome of a decision. Updates the DB and appends `## Outcome` to the molecule markdown. Supports partial slug matching (e.g. `move-to-bangkok` matches `decision-should-i-move-to-bangkok`).

### eureka patterns

Analyze decision-making patterns from resolved decisions. Shows:
- Total resolved vs unresolved decisions
- Average resolution time (days)
- Recommendation vs outcome alignment
- Pending decisions with age

Needs at least 1 resolved decision. Value grows over time.

### eureka lint [--report] [--deep] [--max-pairs N]

Brain health checks. Without `--deep`: pure computation (no LLM).
- **Orphans** — atoms with no inbound edges and no molecule membership
- **Broken links** — `[[wikilinks]]` pointing to non-existent atoms
- **Duplicates** — atom pairs with cosine > 0.95
- **Missing frontmatter** — atoms without type, tags, or date fields
- **Health score** — 0-100 composite metric

With `--deep`: adds LLM-judged checks:
- **Contradictions** — pre-filters pairs by cosine (0.3-0.85), LLM judges logical conflicts
- **Stale claims** — atoms with dates/numbers/temporal language, LLM judges if outdated
- **Knowledge gaps** — concepts `[[wikilinked]]` in 3+ atoms with no dedicated atom

`--report` writes a markdown report to `brain/_lint/YYYY-MM-DD.md`.

### eureka trends [--window N] [--compare N]

Compare tag frequency between two time windows (default 30 days each). Shows:
- Rising/falling tags
- New/disappeared tags
- Activity type shifts (ask, decide, etc.)

Needs atoms with varied `created_at` dates to be meaningful.

### eureka revisit [--count N]

Surface old atoms (30+ days) that are semantically close to your recent activity (last 14 days). Computes centroid of recent activity embeddings and finds distant atoms nearest to it.

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

Uses **Gemini Embedding 001** (3072-dim, #1 MTEB). Requires `GEMINI_API_KEY` in env or brain `.env` file.

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
2. `lint` — orphans, broken links, duplicates
3. `lint --deep` — contradictions, stale claims, gaps (weekly, costs ~$0.50)
4. `reflect` — check blind spots
5. `trends` — is focus shifting?
6. `revisit` — old atoms worth re-reading?
7. Review unreviewed molecules
8. `patterns` — how are past decisions holding up?
9. Backup before new ingests
10. `discover --count 20` after each ingest

## Error Handling

All errors include a suggestion field:

```json
{"ok": false, "errors": [{"message": "source not found", "suggestion": "Check the file path."}]}
```

Read the suggestion before retrying.

## Typical Workflow

```bash
# One-time setup (see Agent Onboarding Flow above for details)
eureka init ~/brain
echo 'GEMINI_API_KEY=AIza...' > ~/brain/.env
eureka setup --brain-dir ~/brain --provider claude-cli --model sonnet
export EUREKA_BRAIN=~/brain

# Build the brain
eureka ingest ~/Books/book.pdf
eureka ingest arxiv:1706.03762 --paper
eureka discover --count 20
eureka serve                            # review in browser

# Thought partner
eureka ask "How do habits form?"
eureka decide "Should I focus on YouTube or LinkedIn?"
eureka resolve decision-should-i-focus --outcome "YouTube grew faster"
eureka patterns

# Maintenance
eureka lint --deep
eureka trends
eureka revisit
eureka status
```
