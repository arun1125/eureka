# Eureka — Brain CLI + Thought Partner

CLI tool for managing the knowledge graph. Data lives in `../../brain/`.

## Structure
- `eureka/cli.py` — main entry point (all commands)
- `eureka/commands/` — subcommands (ingest, discover, review, etc.)
- `eureka/core/` — atom/molecule CRUD, embedding logic, thought partner features
- `eureka/readers/` — file parsers for ingestion
- `eureka/dashboard/` — brain stats and visualization

## Key Facts
- ~600 atoms (markdown files in `../../brain/`), ~110 molecules (in `../../brain/molecules/`)
- Embeddings: Gemini Embedding 001 (3072-dim), stored in brain.db (22MB SQLite)
- `pyproject.toml` defines the package — install with `pip install -e .`
- Tests in `tests/`, plans in `plans/`, docs in `docs/`, demos in `demos/`

## Core Modules

| Module | What it does |
|--------|-------------|
| `core/ask.py` | Graph-aware retrieval (nearest + 1-hop + molecules + tensions + profile reranking) |
| `core/decide.py` | Structured decision support (for/against/tensions/unknowns via LLM) |
| `core/resolve.py` | Decision outcome tracking + pattern analysis |
| `core/lint.py` | Mechanical brain health (orphans, broken links, duplicates, missing frontmatter) |
| `core/lint_llm.py` | LLM-judged health (contradictions, stale claims, knowledge gaps) |
| `core/temporal.py` | Trends, revisit, staleness — temporal reasoning over the graph |
| `core/scorer.py` | IT metric scoring (coherence × novelty × emergence × diversity × feedback × profile) |
| `core/embeddings.py` | Gemini embedding, cosine similarity, vector packing |
| `core/db.py` | SQLite schema, migrations, table compat (atoms vs notes) |
| `core/dump.py` | Raw text → atom extraction via LLM |
| `core/llm.py` | Pluggable LLM backends (10 providers) |

## Thought Partner Plan — COMPLETE

All 7 phases shipped (2026-04-16/17). See `plans/PLAN-thought-partner.md`.

| Phase | Command | Module |
|-------|---------|--------|
| 0 | `eureka decide` | `core/decide.py` |
| 1 | Wiki scaffolding | `brain/SCHEMA.md`, `index.md`, `log.md` |
| 2 | `eureka lint` | `core/lint.py` |
| 3 | `eureka trends`, `eureka revisit` | `core/temporal.py` |
| 4 | Profile scoring | `core/scorer.py`, `core/ask.py` |
| 5 | `eureka lint --deep` | `core/lint_llm.py` |
| 6 | `eureka resolve`, `eureka patterns` | `core/resolve.py` |

31 tests across 5 files, all passing.

## Gotchas
- Atoms live at the brain root as `.md` files, NOT in `brain/atoms/` (that folder is empty)
- `AGENTS.md` describes how other agents should install and use eureka
- Some brains use a `notes` table instead of `atoms` — `db.atom_table(conn)` handles this
- `brain/index.md` was bootstrapped from slugs, not real titles — rebuild on next ingest
