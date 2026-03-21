# Handoff: Eureka v3 Build Session

**Date:** 2026-03-21
**Duration:** ~4 hours
**Repo:** https://github.com/arun1125/eureka (pushed, 17 commits)

## What Was Built

Eureka v3 — a CLI knowledge graph tool that's also a thought partner. Built from scratch using Matt Pocock's TDD process (ubiquitous language → plan → vertical slices → red-green-refactor).

### Engine (34 Python files, 117 tests)

| Layer | What |
|-------|------|
| CLI | 10 commands: init, ingest, discover, ask, dump, profile, reflect, review, status, serve |
| Core | db, parser, index, embeddings, linker, extractor, discovery (8 methods), scorer, ask, dump, profile, pushback, reflect, activity, llm |
| Readers | PDF (pymupdf), EPUB (zipfile), TXT |
| LLM | Kimi K2.5 (Moonshot AI API), Gemini CLI fallback |
| Dashboard | Single-page app: graph (D3 force + zoom/pan), search (tag filters), molecules (sort/expand), review (3-way) |
| Server | Python stdlib HTTP, JSON API: /api/stats, /api/graph, /api/search, /api/molecules, /api/profile, /api/activity, /api/reflect, /api/atom/<slug>, /api/review/<slug> |

### Discovery Methods (8)

triangle, v-structure, walk (3-5 atoms), bridge, antipodal, void, cluster-boundary, residual. Adaptive thresholds for dense brains.

### Scoring

coherence × novelty × emergence^1.5 × source_diversity × size_bonus → 0-100. Source diversity uses real book sources from atoms.source_title column.

### v3 Thought Partner Features

- `eureka dump` — extract atoms from freeform text, find connections/tensions/gaps/pushback
- `eureka profile` — interview questions → extract profile atoms → link to brain
- `eureka reflect` — brain-wide self-assessment (active topics, blind spots, goal alignment, molecules to revisit)
- Enhanced `eureka ask` — profile context, reframes from V-structures, action suggestions
- Pushback engine — contradiction detection, pattern detection (3+ dumps over 2+ weeks), goal-reality gap, historical contradictions

## Auggie's Brain (test project)

Location: `/tmp/auggie-brain/` (TEMPORARY — will be lost on restart)

| Metric | Value |
|--------|-------|
| Atoms | 90 |
| Molecules | 131 |
| Edges | 900 (top-10 per atom) |
| Sources | 6 books |

### Sources Ingested
1. **Atomic Habits** — James Clear (19 atoms)
2. **Meditations** — Marcus Aurelius (13 atoms)
3. **Psycho-Cybernetics** — Maxwell Maltz (13 atoms)
4. **Reality Transurfing Steps I-V** — Vadim Zeland (17 atoms)
5. **The Law of Success** — Napoleon Hill (16 atoms)
6. **Bible (selected)** — Proverbs, Ecclesiastes, James, Romans 12, Psalms (16 atoms)

### Extraction Method
- **Model:** Kimi K2.5 via Moonshot AI API (key: `sk-rt9ImtmsbGgB1MtBvEpaI3xDKv5quHnRselLqdXlkfJZiKiR`)
- **Prompt pattern:** Book-specific prompts with seeded key concepts, filtered for self-development/entrepreneurship
- **Molecule writing:** Mix of Kimi K2.5 (~90) and Claude subagents (~40)
- **Extract script:** `/tmp/eureka-test/extract_all.py` (has all the book-specific prompts)

### Quality Findings
- Kimi K2.5 with targeted prompts produces much better atoms than generic Gemini Flash extraction
- The prompt matters more than the model — seeding key concepts and filtering for the user's niche is the quality lever
- Cross-source molecules (Bible ↔ Transurfing ↔ Atomic Habits) are the most interesting
- Score range: 41-87 after source diversity scoring
- Similarity range in this brain: 0.475-0.85 (dense, all self-dev books) — required adaptive thresholds

## Next Session: Make Auggie's Brain Awesome

The user wants to package Augustin's brain as a gift. Two goals:
1. Make the brain itself excellent (better atoms, better molecules, better presentation)
2. Improve Eureka in the process (whatever we build for Auggie becomes a feature)

### Open Questions for Next Session
- What does "awesome" look like for Augustin? What should he experience?
- Should the brain be a standalone zip (brain.db + atoms/ + molecules/ + dashboard)?
- Does Augustin need his own profile atoms in the brain?
- Should molecules have source attribution (which books contributed)?
- Is the dashboard the primary interface, or does Augustin use an agent (Claude Code, etc.)?

### Things That Could Make It Better
- **More books** — what else is Augustin reading/interested in?
- **Better molecule quality** — Claude writes better molecules than Kimi. Could re-write all with Claude subagents.
- **Source attribution on atoms** — show which book each atom came from in the dashboard
- **Molecule constituent display** — show the actual atom bodies inside molecule cards, not just slugs
- **Dashboard polish** — better graph colors, source-based coloring instead of tag-based, search improvements
- **Walkthrough mode** — guided tour of the brain's best insights
- **Export** — markdown summary of top molecules, printable

### Known Issues
- Pushback on `ask` is disabled (cosine similarity can't distinguish agreement from contradiction without LLM)
- URL and YouTube readers are stubs
- `--brain-dir` required on every command (should default to config)
- Dashboard doesn't auto-refresh after review
- Auggie's brain is in /tmp (will be lost) — needs to be copied somewhere permanent before next session

### Critical: Save Auggie's Brain
```bash
# Copy before it's lost
cp -r /tmp/auggie-brain ~/Desktop/auggie-brain-backup
```

## Files to Read First Next Session
1. `SPEC-v3.md` — the thought partner spec
2. `plans/PLAN-v3.md` — implementation plan (all slices done)
3. `UBIQUITOUS_LANGUAGE.md` — domain glossary
4. `README.md` — current feature list
5. `/tmp/eureka-test/extract_all.py` — the extraction script with book-specific prompts
