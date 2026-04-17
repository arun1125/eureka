# PLAN — Eureka v1.0: Thought Partner

Supersedes PLAN-llm-wiki.md (Karpathy's ideas folded into Phase 2).

**Status: COMPLETE** — All 7 phases shipped 2026-04-16/17.

## Vision

Eureka shifts from "knowledge graph CRUD" to "thought partner that talks back."
The human curates sources and asks questions. The brain maintains itself, surfaces
tensions, and helps make decisions.

## Phases (all shipped)

### Phase 0 — `eureka decide` ✓
Structured decision support. `core/decide.py`, 6 tests.
- Graph-aware retrieval → atom body reading → LLM structured analysis
- For/against/tensions/unknowns/recommendation
- Files as molecule + logs to decisions table
- CLI: `eureka decide "question" [--context "..."] [--no-file]`

### Phase 1 — Karpathy wiki layer ✓
Brain scaffolding. Committed to parent Agents repo.
- `brain/SCHEMA.md` — contract for LLM maintenance
- `brain/index.md` — 472-atom alphabetical index
- `brain/log.md` — append-only ingest log
- `brain/sources/.gitkeep`

### Phase 2 — `eureka lint` v1 (mechanical) ✓
Pure computation, no LLM. `core/lint.py`, 6 tests.
- Orphans, broken wikilinks, duplicates (cosine > 0.95), missing frontmatter
- Health score 0-100, markdown report via `--report`

### Phase 3 — Temporal reasoning ✓
`core/temporal.py`, 5 tests.
- `eureka trends` — tag frequency shift between time windows
- `eureka revisit` — old atoms near recent activity centroid
- `staleness()` — atoms dormant beyond threshold

### Phase 4 — Profile-integrated scoring ✓
Modified `core/scorer.py` + `core/ask.py`, 6 tests.
- `profile_multiplier()` — 1.0-1.5x boost for goal-aligned atoms
- `ask()` re-ranks top 10 → top 5 with 10% profile blend

### Phase 5 — `eureka lint --deep` (LLM-judged) ✓
`core/lint_llm.py`, 6 tests.
- Contradictions: cosine 0.3-0.85 pre-filter → LLM judges batches of 10
- Stale claims: temporal regex pre-filter → LLM judges
- Knowledge gaps: wikilinks in 3+ atoms with no dedicated atom (no LLM)
- CLI: `eureka lint --deep [--max-pairs N]`

### Phase 6 — `eureka resolve` + `eureka patterns` ✓
`core/resolve.py`, 8 tests.
- `eureka resolve <slug> --outcome "..."` — records outcome, appends to molecule .md
- Partial slug matching
- `eureka patterns` — resolution time, recommendation-vs-outcome, pending decisions

## Test Suite
31 tests across 5 test files, all passing.
```bash
uv run python -m pytest tests/test_decide.py tests/test_lint.py tests/test_temporal.py tests/test_lint_llm.py tests/test_resolve.py -v
```

## Resolved Questions
1. **Source backfill:** No. Start compounding from today.
2. **Atom ownership:** Human atoms stay human-owned. LLM additions tagged.
3. **Query file-back default:** ON for `decide`, OFF for `ask`.
4. **LLM model allocation:** Decide = Sonnet. Lint v2 = Haiku.
