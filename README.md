# Eureka

A CLI tool for AI agents that turns raw sources into a knowledge graph of atomic ideas and synthesized insights. Also a thought partner — dump your thinking, get pushback, find blind spots.

**The tool computes. The agent thinks. The human decides.**

## What it does

Eureka ingests sources (books, PDFs, EPUBs, notes), extracts atomic ideas, links them by semantic similarity, and discovers non-obvious connections using embedding geometry and information theory.

- **Atoms** — single concepts written as opinionated claims
- **Molecules** — insights synthesized from 2+ atoms that say something none of them say alone
- **8 Discovery Methods** — triangles, V-structures, random walks, bridges, antipodal pairs, voids, cluster-boundary, residuals
- **Scoring** — coherence × novelty × emergence × source diversity, normalized 0-100
- **Thought Partner** — brain dumps, profile, pushback (contradictions, patterns, goal gaps), reflect

## Install

```bash
pip install git+https://github.com/arun1125/eureka.git
```

## Quick start

```bash
# Initialize a brain
eureka init ~/brain

# Ingest sources (PDF, EPUB, TXT)
eureka ingest ~/Downloads/book.pdf --brain-dir ~/brain
eureka ingest ~/Downloads/notes.txt --brain-dir ~/brain

# Check brain status
eureka status ~/brain

# Discover new insights (needs LLM — set KIMI_API_KEY or use gemini CLI)
eureka discover ~/brain --count 20

# Query the brain
eureka ask "how should I price my services" --brain-dir ~/brain

# Brain dump — think out loud, get connections + tensions + pushback
eureka dump "I think niching down is overrated" --brain-dir ~/brain

# Profile — build a user profile for personalized responses
eureka profile --brain-dir ~/brain              # get questions
eureka profile --answers "I'm building..." --brain-dir ~/brain  # process answers

# Reflect — brain-wide self-assessment
eureka reflect --brain-dir ~/brain

# Review pending molecules
eureka review some-molecule-slug yes --brain-dir ~/brain

# Visual dashboard
eureka serve ~/brain --port 8769
```

## LLM Configuration

Eureka needs an LLM for extraction and molecule writing. Set one:

```bash
# Kimi K2.5 (free tier, recommended)
export KIMI_API_KEY=sk-your-key-here

# Or install Gemini CLI (fallback)
# gemini CLI must be in PATH
```

## For agents

Every command outputs JSON to stdout. Progress goes to stderr. See [AGENTS.md](AGENTS.md) for the full agent interface.

```json
{"ok": true, "command": "ask", "data": {"nearest": [...], "tensions": [...], "profile_context": [...], "reframes": [...], "pushback": [...]}}
```

Exit codes: 0=success, 1=failure, 2=usage error, 3=not found, 5=conflict.

## Dashboard

`eureka serve` starts a localhost dashboard with 4 tabs:

- **Graph** — force-directed layout with zoom/pan, click any node to see details, community coloring by tag
- **Search** — search by text or filter by tag, click results to open detail panel
- **Molecules** — browse all molecules with ELI5, sort by score/newest/A-Z/shuffle, click to expand
- **Review** — three-way review: "I already know this" / "New & interesting" / "Doesn't excite me"

## Discovery Methods

| Method | What it finds |
|--------|--------------|
| Triangle | 3 atoms all pairwise similar — agreement across sources |
| V-structure | A and B disagree but both connect to bridge C — tension |
| Walk | Random walk on the graph — distant but reachable combinations |
| Bridge | Atoms connecting two otherwise separate communities |
| Antipodal | Max semantic distance but shared structural path |
| Void | Semantic gaps between clusters — ideas that should exist but don't |
| Cluster-boundary | Atoms at the edge of their community, near another |
| Residual | Underconnected atoms with untapped potential |

## How it works

```
Source → Chunk → Extract Atoms → Index → Embed → Link → Discover → Score → Write Molecule
         ~~~~~~~~~~~~LLM~~~~~~~~~~~~   ~~~~~deterministic~~~~~   ~~~~~~~~~~~LLM~~~~~~~~~~~~
```

Three steps use an LLM. Everything else is deterministic: embedding geometry, graph topology, information theory.

## License

MIT
