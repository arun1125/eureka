# PLAN — Karpathy LLM Wiki for Eureka

Source: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

## Core shift

Today eureka is CRUD + semantic search over ~470 atoms. Karpathy's idea reframes the
brain as a **persistent, compounding wiki** that the LLM continuously maintains. The
human curates raw sources and asks questions; the LLM does the bookkeeping (updating
pages, fixing cross-refs, resolving contradictions, filling gaps).

Mapping onto what we already have:

| Karpathy layer | Eureka today | Gap |
|---|---|---|
| Raw sources (immutable) | nothing — atoms are hand-written | need `brain/sources/` |
| Wiki pages | atoms (`brain/*.md`) + molecules | already good |
| Schema | `brain/README.md`-ish, implicit | need explicit `SCHEMA.md` |
| Ingest | one-shot atom create | need multi-file pass |
| Query | `eureka search` (retrieval only) | need "file answer back as atom" |
| Lint | nothing | new command |

## Deliverables

### 1. `brain/sources/` + `brain/SCHEMA.md`

- `brain/sources/` — immutable raw inputs (tweets, PDFs, articles, transcripts).
  Filename convention: `YYYY-MM-DD_<slug>.<ext>`. Never edited after write.
- `brain/SCHEMA.md` — the contract the LLM reads before every ingest/lint run.
  Defines: atom naming, frontmatter fields, linking syntax, molecule promotion
  rules, contradiction-resolution policy, staleness thresholds.

### 2. `eureka ingest <source>`

Not "create one atom." A multi-file pass:

1. Read source → write to `brain/sources/` if not already there.
2. Extract claims, entities, concepts.
3. Semantic search existing atoms for each extracted item.
4. For each match: **update** the atom (add claim, add backlink to source).
5. For each miss above a threshold: **create** a new atom.
6. Update any molecules whose member atoms changed.
7. Print a diff summary (files touched, atoms created, links added).

Flags: `--dry-run` (show diff, don't write), `--max-files N` (safety cap).

### 3. `eureka lint`

Periodic health check. Reports (and optionally fixes with `--fix`):

- **Contradictions** — atoms making opposite claims (semantic + LLM judge).
- **Stale claims** — atoms with dated assertions older than N months.
- **Orphans** — atoms with zero backlinks and zero molecule membership.
- **Gaps** — concepts mentioned across ≥3 atoms but with no atom of their own.
- **Broken links** — `[[atom]]` references to nonexistent files.
- **Duplicate atoms** — high cosine similarity pairs.

Output: markdown report to `brain/_lint/YYYY-MM-DD.md`.

### 4. `eureka query <question>` (upgrade, not new)

Current `search` returns atoms. New behavior:

1. Retrieve relevant atoms (existing logic).
2. Synthesize an answer.
3. If the answer is non-trivial and novel, **file it back** as a new atom or
   append to a synthesis molecule — so the next query benefits.
4. Always cite source atoms in output.

Flag: `--no-file` to preserve today's read-only behavior.

## Implementation order

1. **Write `SCHEMA.md` first.** Everything else depends on it. Draft it by
   reading current atom conventions out of `brain/` and codifying them.
2. **`brain/sources/` folder + ingest v1** — read one source, create/update
   atoms, no molecule logic yet. Ship behind `--dry-run` default.
3. **Lint v1** — orphans + broken links + duplicates only (cheap, mechanical).
   Skip contradictions/gaps until schema is battle-tested.
4. **Query upgrade** — file-back behavior. Opt-in flag first, default later.
5. **Lint v2** — contradictions, stale claims, gaps (LLM-judged, expensive).
6. **Ingest v2** — molecule updates, backfill old sources in `brain/sources/`.

## Critical files

- `eureka/cli.py` — register new subcommands
- `eureka/commands/ingest.py` — new
- `eureka/commands/lint.py` — new
- `eureka/commands/query.py` — new (or upgrade `search.py`)
- `eureka/core/wiki.py` — new: schema loader, multi-file update primitive
- `brain/SCHEMA.md` — new
- `brain/sources/` — new folder

## Open questions for Arun

1. **Source backfill.** Do existing atoms get retro-linked to sources, or does
   the wiki only start compounding from today forward?
2. **Write blast radius.** Ingest touching 10-15 files per source is powerful
   but scary. Default to `--dry-run` + manual approve, or auto-commit to a
   `wiki/<date>` git branch?
3. **Schema authority.** When `SCHEMA.md` and existing atoms disagree, does
   lint rewrite atoms to match, or does it flag and wait?
4. **LLM model.** Ingest and lint are expensive. Opus for ingest, Haiku for
   lint mechanical checks, Sonnet for judge calls?

## Non-goals

- Replacing semantic search. Embeddings stay; the wiki layer sits on top.
- Building a UI. CLI + markdown files only.
- Auto-ingesting everything Arun reads. Sources are explicitly added.
