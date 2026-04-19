# Eureka Thought Partner — Handover

Session: 2026-04-16 + 2026-04-17

## What shipped

### Session 1 (2026-04-16) — Phases 0-4, pushed to `arun1125/eureka`

| Commit | Phase | Files |
|--------|-------|-------|
| `9ea28e7` | Phase 0: `eureka decide` | `core/decide.py`, `cli.py`, `core/db.py`, `tests/test_decide.py` |
| `f9f707e` | Phase 2: `eureka lint` | `core/lint.py`, `cli.py`, `tests/test_lint.py` |
| `c20deaf` | Phase 3: `eureka trends/revisit` | `core/temporal.py`, `cli.py`, `tests/test_temporal.py` |
| `58e95a7` | Phase 4: Profile scoring | `core/scorer.py`, `core/ask.py`, `tests/test_profile_scoring.py` |

Plus 1 commit to the parent Agents repo (Phase 1):
- `brain/SCHEMA.md`, `brain/index.md`, `brain/log.md`, `brain/sources/.gitkeep`

### Session 2 (2026-04-17) — Phases 5-6

| Phase | Files |
|-------|-------|
| Phase 5: `eureka lint --deep` | `core/lint_llm.py`, `cli.py`, `tests/test_lint_llm.py` |
| Phase 6: `eureka resolve` + `eureka patterns` | `core/resolve.py`, `cli.py`, `tests/test_resolve.py` |

## What to test manually

### `eureka decide` (most important — the whole point)
```bash
eureka decide "Should I focus on YouTube or LinkedIn for the next 3 months?" --brain-dir ~/brain
```
- Does it pull relevant atoms? (check `atoms_consulted` in output)
- Does the for/against/tensions/unknowns structure make sense?
- Does it write a molecule to `brain/molecules/decision-*.md`?
- Try with `--context "I have 10k LinkedIn followers and 200 YouTube subs"`
- Try with `--no-file` to verify it doesn't write anything

### `eureka lint`
```bash
eureka lint --brain-dir ~/brain
eureka lint --brain-dir ~/brain --report
```
- How many orphans/broken links/duplicates does the real brain have?
- Does `--report` create `brain/_lint/2026-04-17.md`?
- Check if the health score feels right

### `eureka lint --deep` (NEW — Phase 5)
```bash
eureka lint --brain-dir ~/brain --deep
eureka lint --brain-dir ~/brain --deep --max-pairs 20
```
- Does it find contradictions between atoms? (pre-filters cosine 0.3-0.85, then LLM judges)
- Does it flag stale claims? (atoms with dates, percentages, "currently" language)
- Does it find knowledge gaps? (concepts [[wikilinked]] in 3+ atoms but missing their own atom)
- Cost: depends on atom count. ~$0.50/run with Haiku on ~500 atoms.

### `eureka resolve` (NEW — Phase 6)
```bash
# First, make a decision
eureka decide "Should I focus on YouTube?" --brain-dir ~/brain

# Later, record what happened
eureka resolve decision-should-i-focus-on-youtube --outcome "Focused on YouTube for 2 months, grew from 200 to 1.2k subs" --brain-dir ~/brain
```
- Does it update the decision in the DB?
- Does it append an `## Outcome` section to the molecule .md file?
- Try partial slug match: `eureka resolve focus-on-youtube --outcome "..." --brain-dir ...`

### `eureka patterns` (NEW — Phase 6)
```bash
eureka patterns --brain-dir ~/brain
```
- Shows resolved vs unresolved decision counts
- Average resolution time
- Lists pending decisions with age
- Needs at least 1 resolved decision to show analysis (otherwise just a message)

### `eureka trends`
```bash
eureka trends --brain-dir ~/brain
eureka trends --brain-dir ~/brain --window 14
```
- Does it show meaningful focus shifts? (needs atoms with varied created_at dates)
- If all atoms have the same date, it'll be empty — that's expected

### `eureka revisit`
```bash
eureka revisit --brain-dir ~/brain
```
- Does it surface old atoms relevant to recent activity?
- Needs activity log entries to work — if you haven't been using `eureka ask` much, it'll be empty

### Profile scoring (implicit — no new CLI command)
- Run `eureka ask` with and without profile data
- If you have profile entries (`eureka profile --brain-dir ...`), atoms near your goals should rank slightly higher
- Hard to A/B test manually, but at minimum verify `ask` doesn't crash

## Known risks

1. **`decide` prompt quality.** The LLM prompt in `decide.py:_build_prompt()` is a first draft. It tells the LLM to return JSON but some models wrap in markdown anyway — the parser handles `` ```json `` blocks and raw `{...}` extraction as fallbacks, but edge cases may exist.

2. **`lint` false positives on orphans.** Atoms with only outbound edges but no inbound edges show as orphans. This is technically correct but may flag lots of leaf atoms that are fine.

3. **Profile scoring is a gentle 10% nudge in `ask.py`.** If it doesn't feel like it's doing anything, the weight might need increasing. Conversely, if results feel biased, lower it.

4. **`trends` needs varied atom dates.** If most atoms were bulk-imported on the same day, the two time windows will be imbalanced. Real value comes after a few weeks of incremental ingestion.

5. **`brain/index.md` was bootstrapped from slug names, not actual titles.** The titles are title-cased slugs, not the real H1 from each atom. First real ingest should rebuild it properly.

6. **`lint --deep` contradiction band (0.3-0.85).** If this is too wide you'll burn tokens on irrelevant pairs. If too narrow you'll miss subtle contradictions. Tune `--max-pairs` to control cost.

7. **`lint --deep` stale claims regex.** The temporal pattern matcher catches "2019", "currently", "$X", etc. but may miss domain-specific staleness (e.g. "React 17" without a year). LLM compensates but the pre-filter affects what it sees.

8. **`patterns` needs volume.** Pattern detection is basic counting right now — recommendation-vs-outcome alignment, resolution time. Real insight comes after 10+ resolved decisions.

## All phases complete

The original 7-phase plan (PLAN-thought-partner.md) is now fully implemented:
- Phase 0: `eureka decide` (structured decision support)
- Phase 1: Wiki scaffolding (SCHEMA.md, index.md, log.md, sources/)
- Phase 2: `eureka lint` v1 (mechanical checks)
- Phase 3: `eureka trends` + `eureka revisit` (temporal reasoning)
- Phase 4: Profile-integrated scoring
- Phase 5: `eureka lint --deep` (LLM-judged contradictions, stale claims, gaps)
- Phase 6: `eureka resolve` + `eureka patterns` (decision outcome loop)

## Test suite
```bash
cd tools/eureka
uv run python -m pytest tests/test_decide.py tests/test_lint.py tests/test_temporal.py tests/test_lint_llm.py tests/test_resolve.py -v
```
All 31 tests passing as of this handover.
