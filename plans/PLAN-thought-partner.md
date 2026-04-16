# PLAN — Eureka v1.0: Thought Partner

Supersedes PLAN-llm-wiki.md (Karpathy's ideas folded into Phase 2).

## Vision

Eureka shifts from "knowledge graph CRUD" to "thought partner that talks back."
The human curates sources and asks questions. The brain maintains itself, surfaces
tensions, and helps make decisions.

## Revised Phase Order

Ship value first, plumbing second.

### Phase 0 — `eureka decide` (THE KILLER FEATURE)
Structured decision support using existing 600+ atoms.

Pipeline:
1. Embed the question → retrieve relevant atoms (reuse ask.py)
2. Pull profile goals/values via get_relevant_profile()
3. Find V-structures (tensions) near the question
4. Read atom bodies for retrieved + tension atoms
5. LLM call: given atoms + profile + tensions, produce structured output:
   - **For:** arguments supporting each option
   - **Against:** arguments against each option
   - **Tensions:** where your existing knowledge disagrees with itself
   - **Unknowns:** what the brain doesn't have enough atoms to judge
   - **Recommendation:** weighted by profile goals
6. File the decision frame back as a molecule (type: decision)
7. Log to decisions table for outcome tracking

New files:
- `eureka/core/decide.py` — decision pipeline
- DB migration: `decisions` table (question, result_json, molecule_slug, outcome, resolved_at, created_at)

CLI: `eureka decide "Should I do X or Y?" --brain-dir <dir>`
Flags: `--no-file` (don't save as molecule), `--context "extra context"`

### Phase 1 — Weekly digest (passive value)
Automated weekly summary surfacing what changed and what matters.

Pipeline:
1. Query activity log for past 7 days
2. New atoms, new molecules, reviewed molecules
3. Cross-reference with profile goals
4. Detect: focus shifts, blind spots widening/closing, stale decisions
5. LLM call: synthesize into "here's what your brain learned this week"

New files:
- `eureka/core/digest.py` — weekly synthesis
- Wire as cron job or SessionStart hook

CLI: `eureka digest --brain-dir <dir> [--days 7]`

### Phase 2 — Karpathy wiki layer
Foundation for self-maintaining brain.

- `brain/sources/` — immutable raw inputs
- `brain/SCHEMA.md` — contract for LLM maintenance
- `brain/index.md` — maintained index, updated on every ingest (from Karpathy)
- `brain/log.md` — append-only chronological ingest log (from Karpathy)
- Ingest v2: multi-file pass (update existing atoms, not just create new)
- `--dry-run` default, git auto-commit per ingest

### Phase 3 — `eureka lint` v1 (mechanical)
No LLM, pure computation:
- Orphaned atoms (zero backlinks, zero molecule membership)
- Broken wikilinks ([[slug]] to nonexistent atoms)
- Duplicate atoms (cosine similarity > 0.95)
- Missing frontmatter fields

Output: markdown report to `brain/_lint/YYYY-MM-DD.md`

### Phase 4 — Temporal reasoning
- Atom staleness scores (decay over time, refreshed on citation)
- `eureka trends` — focus shifts over time windows
- `eureka revisit` — old atoms newly relevant to recent activity
- Needs enough history to be useful — Phase 2 ingest builds this

### Phase 5 — Profile-integrated scoring
- Profile goals weight discovery scoring (scorer.py multiplier)
- `ask` and `decide` prioritize atoms near stated goals
- Discovery surfaces molecules aligned with current objectives

### Phase 6 — `eureka lint` v2 (LLM-judged)
- Contradictions: pre-filter by cosine (0.5-0.85), LLM judges ~500 pairs
- Stale claims: atoms with dated assertions older than threshold
- Knowledge gaps: concepts mentioned across 3+ atoms with no dedicated atom
- Cost: ~$0.50/run with Haiku

### Phase 7 — `eureka resolve` (decision outcomes)
Closes the decide loop:
- `eureka resolve <decision-slug> --outcome "what happened"`
- Links outcome back to the decision molecule
- Over time: pattern detection on decision quality
- "You tend to overthink X-type decisions" / "Your instincts on Y are good"

## Open Questions
1. **Source backfill:** Do existing 600 atoms get retro-linked to sources?
   Recommendation: no. Start compounding from today. Backfill is a separate project.
2. **Atom ownership:** Existing hand-written atoms stay human-owned. LLM additions
   are clearly tagged (source: "eureka-ingest" or "eureka-decide"). Lint never
   auto-edits human atoms — it flags and waits.
3. **Query file-back default:** ON for `decide`, OFF for `ask` (preserving current
   behavior). Revisit after Phase 0 usage.
4. **LLM model allocation:** Decide/digest = Sonnet. Lint v2 = Haiku. Ingest = Sonnet
   for extraction, Haiku for match decisions.

## Critical Path
Phase 0 is the only thing that matters right now. It's 1 new file (decide.py),
1 DB migration (decisions table), and ~50 lines in cli.py. Everything else is
Phase 2+.
