# Eureka — Implementation Plan

Tracer-bullet vertical slices. Each slice touches DB → core → CLI → test and is demoable on its own. TDD per slice: write one test → make it pass → repeat.

No migration from SecondBrainKit. Clean project, clean start.

---

## Slice 1: Init + Status (Foundation)

**Demo:** `eureka init ~/test-brain && eureka status` → JSON output showing an empty brain.

| Layer | What |
|-------|------|
| DB | `open_db()` creates all tables. `get_stats()` returns counts. |
| Core | `output.py` envelope/emit. `db.py` schema + helpers. |
| CLI | `eureka init [dir]` — creates dir, brain.db, brain.json, git init, writes global config. `eureka status` — reads stats, returns JSON envelope. |
| Test | `test_init.py` — init creates dir structure, idempotent re-init. `test_status.py` — empty brain returns zeros. |

**Exit criteria:** Both commands produce valid JSON envelopes. Tests green.

---

## Slice 2: Parser + Index (Read Atoms from Disk)

**Demo:** Drop 3 .md files in atoms/ → `eureka status` shows 3 atoms with tags and edges.

| Layer | What |
|-------|------|
| DB | Insert atoms, tags, note_tags, edges. FTS triggers fire. |
| Core | `parser.py` — read .md file, extract title/body/wikilinks/tags. `index.py` — sync .md files to DB (upsert atoms, compute body_hash, resolve wikilinks to edges). |
| CLI | `eureka status` now shows real atom count. Internal `rebuild_index()` called by init and ingest. |
| Test | `test_parser.py` — parse title, body, wikilinks, tags from .md. `test_index.py` — sync 3 files, verify DB rows, verify edges from wikilinks. |

**Exit criteria:** Parser extracts all fields. Index populates DB correctly. FTS search works.

---

## Slice 3: Embeddings + Linking

**Demo:** 10 atoms in brain → `eureka status` shows edges with similarity scores. Top-5 edges per atom.

| Layer | What |
|-------|------|
| DB | Embeddings table populated. Edges have non-null similarity. |
| Core | `embeddings.py` — fastembed wrapper, cache in DB, cosine_sim. `linker.py` — for each atom, find top-5 by cosine sim, upsert edges. |
| CLI | Linking happens inside `rebuild_index()` after embedding. |
| Test | `test_embeddings.py` — embed text, cache hit, cosine sim correct. `test_linker.py` — 10 atoms produce max 50 edges, similarities in [0,1]. |

**Exit criteria:** Embeddings cached. Each atom has ≤5 edges. Similarity scores correct.

---

## Slice 4: Readers (Source → Chunks)

**Demo:** `eureka ingest ~/test.pdf` → chunks printed to stderr, source row in DB.

| Layer | What |
|-------|------|
| DB | Source row created with title, type, chunk_count. |
| Core | `readers/` — base reader interface + text/pdf/url/youtube readers. Source detection from path/URL. |
| CLI | `eureka ingest <source>` — detect type, chunk, store source row. (No LLM extraction yet — just chunking.) |
| Test | `test_readers.py` — text reader chunks correctly. `test_ingest_source.py` — source row created with correct type. |

**Exit criteria:** Each reader returns chunks. Source row in DB. Type detection correct.

---

## Slice 5: LLM Extraction (Chunks → Atoms)

**Demo:** `eureka ingest test.txt` → atoms extracted, .md files written, indexed, embedded, linked. Full ingest pipeline.

| Layer | What |
|-------|------|
| DB | Atoms with source_id. Source.atom_count updated. |
| Core | `llm.py` — pluggable LLM client (Gemini default). `extractor.py` — extraction prompt + response parsing → atoms[]. |
| CLI | `eureka ingest` now does the full pipeline: chunk → extract → write .md → index → embed → link → report. |
| Test | `test_extractor.py` — mock LLM, verify prompt sent, parse response into atoms. `test_ingest_full.py` — end-to-end with mock LLM. |

**Exit criteria:** Full ingest pipeline works end-to-end. Atoms written to disk and DB. Git commit created.

---

## Slice 6: Discovery + Scoring

**Demo:** `eureka discover` → finds candidates, scores them, surfaces top molecule with ELI5.

| Layer | What |
|-------|------|
| DB | Molecules, molecule_atoms, discovery_runs populated. |
| Core | `discovery.py` — triangle + v-structure finders. `scorer.py` — IT metric (coherence × novelty × emergence), normalized 0-100. `writer.py` — LLM writes molecule body + ELI5. |
| CLI | `eureka discover [--method M] [--count N]` — full discovery pipeline. `eureka ingest` now includes auto-discover after linking. |
| Test | `test_discovery.py` — triangle finder finds known triangle. V-structure finder finds known V. `test_scorer.py` — score is 0-100, known inputs produce expected ranking. `test_discover_cmd.py` — end-to-end with mock LLM. |

**Exit criteria:** Discovery finds candidates from a seeded brain. Scores are 0-100. Top molecule has body + ELI5. Discovery run logged.

---

## Slice 7: Ask (Graph-Aware Retrieval)

**Demo:** `eureka ask "how should I price my services"` → nearest atoms + graph neighbors + molecules + tensions.

| Layer | What |
|-------|------|
| DB | Read-only queries across atoms, edges, molecules, embeddings. |
| Core | `ask.py` — embed question, nearest-5, 1-hop walk, find molecules containing retrieved atoms, find V-structures near question. |
| CLI | `eureka ask "question"` → structured JSON for agent to synthesize. |
| Test | `test_ask.py` — seeded brain, known question returns expected atoms. Graph walk finds neighbor. |

**Exit criteria:** Returns structured results. Graph walk reaches atoms RAG would miss. Tensions surfaced.

---

## Slice 8: Review (Feedback Loop)

**Demo:** `eureka review <slug> yes` → accepted. `eureka review <slug> no` → rejected + .md deleted.

| Layer | What |
|-------|------|
| DB | review_status updated. reviews table logged. Kill list maintained. |
| Core | `review.py` — accept/reject logic, kill list update, git commit. |
| CLI | `eureka review <slug> yes\|no` |
| Test | `test_review.py` — accept keeps molecule, reject deletes .md, review logged, already-reviewed returns exit 5. |

**Exit criteria:** Accept/reject works. Reviews logged. Kill list persists. Git commits created.

---

## Slice 9a: Dashboard — Server + API

**Demo:** `eureka serve` starts, `curl localhost:8765/api/stats` returns brain stats JSON.

| Layer | What |
|-------|------|
| Core | `server.py` — HTTP server, static file serving, JSON API endpoints: `/api/graph`, `/api/search?q=`, `/api/molecules`, `/api/review`, `/api/review/<slug>` (POST), `/api/stats`. |
| CLI | `eureka serve [--port N]` — starts server, blocks until Ctrl+C. |
| Test | `test_server.py` — each endpoint returns correct JSON shape for a seeded brain. POST review updates DB. |

**Exit criteria:** All API endpoints return valid JSON. POST review writes to DB. Server starts/stops cleanly.

---

## Slice 9b: Dashboard — Graph Tab

**Demo:** Open browser → force-directed graph with colored nodes and top-5 edges.

| Layer | What |
|-------|------|
| Frontend | D3 force layout. Node shapes: circles (atoms), triangles (triangle-molecules), V's (V-structure-molecules), diamonds (other molecules). Community colors (muted pastels). Click → detail panel. Hover → highlight neighbors. Legend. Search filter. |
| API | `/api/graph` returns `{nodes: [{slug, type, method, community, ...}], edges: [{source, target, similarity}]}` |

**Exit criteria:** Graph renders with correct shapes and colors. Top-5 edges per node. Click and hover work. Legend visible.

---

## Slice 9c: Dashboard — Search + Molecules Tabs

**Demo:** Type a query → results appear. Switch to Molecules tab → browse all accepted molecules with ELI5.

| Layer | What |
|-------|------|
| Frontend — Search | Full-text search input. Results show: title, snippet, type icon, tags, score. Click → expand full body + linked atoms. |
| Frontend — Molecules | Grid/list of accepted molecules. Each card: title, ELI5, method badge, score, constituent atoms, date. Filter by method/tag/score/date. Sort by score/newest/method. Click → expand with atom bodies. |
| API | `/api/search?q=` returns ranked results. `/api/molecules` returns molecules with atoms and ELI5. |

**Exit criteria:** Search returns relevant results. Molecules tab shows all accepted molecules. Filters and sorting work. ELI5 visible on every card.

---

## Slice 9d: Dashboard — Review Tab

**Demo:** Pending molecules appear as cards. Press Y → accepted. Press N → rejected and disappears.

| Layer | What |
|-------|------|
| Frontend | Pending molecules at top — cards with title, ELI5, method, score, constituent atom bodies. Yes/No buttons + keyboard shortcuts (y/n, arrow keys to navigate). Recent atoms below. Counts: "7 pending · 14 atoms ingested today". |
| API | POST `/api/review/<slug>` with `{decision: "yes"|"no"}`. Response confirms update. |

**Exit criteria:** Keyboard shortcuts work. Yes removes card and updates DB. No removes card, deletes .md, updates DB. Count updates live.

---

## Slice 10: Package + Ship

**Demo:** `pip install git+https://github.com/arunthiru/eureka.git && eureka init ~/brain`

| Layer | What |
|-------|------|
| Package | pyproject.toml final, dashboard assets bundled, entry point works. |
| Docs | README.md (install + quick start), AGENTS.md (agent instructions), LICENSE (MIT). |
| CI | GitHub Actions: pytest on push. |
| Test | Install in fresh venv, run `eureka init`, verify. |

**Exit criteria:** `pip install` works from GitHub. `eureka --help` shows commands. README is clear. CI green.

---

## Slice Order & Dependencies

```
Slice 1 (init+status) ──→ Slice 2 (parser+index) ──→ Slice 3 (embed+link)
                                                            │
Slice 4 (readers) ──────────────────────────────────────────┤
                                                            ▼
                                                    Slice 5 (LLM extract)
                                                            │
                                                            ▼
                                                    Slice 6 (discover+score)
                                                            │
                                            ┌───────────────┼───────────────┐
                                            ▼               ▼               ▼
                                    Slice 7 (ask)   Slice 8 (review)   Slice 9a (API)
                                                                            │
                                                                ┌───────────┼───────────┐
                                                                ▼           ▼           ▼
                                                          9b (graph)  9c (browse)  9d (review UI)
                                                                │           │           │
                                                                └───────────┴───────────┘
                                                                            │
                                                                            ▼
                                                                    Slice 10 (package)
```

Slices 1-3 can proceed without LLM. Slice 4 can run in parallel with 2-3. Slices 7, 8, 9a are independent of each other after 6. Slices 9b-9d are independent of each other after 9a.

## TDD Protocol (per slice)

From Matt Pocock's `tdd` skill:

1. Pick ONE behavior from the slice
2. Write a test that fails (RED)
3. Write the minimum code to pass (GREEN)
4. Refactor if needed
5. Repeat for next behavior
6. Never write tests for internal implementation — test through public interfaces (CLI commands or core function signatures)
7. Each test file mirrors the module it tests

Use Ralph loops: each iteration is one red→green cycle.

## Design-an-Interface Checkpoints

At these points, pause and spawn 3+ parallel sub-agents with radically different designs (Matt Pocock's `design-an-interface`):

- **Before Slice 3:** Embedding/linking interface (how components plug in)
- **Before Slice 6:** Scoring function interface (how custom scorers work)
- **Before Slice 9a:** Dashboard data API (how server exposes brain data)
