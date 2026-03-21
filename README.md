# Eureka

A CLI tool for AI agents that turns raw sources into a knowledge graph of atomic ideas and synthesized insights.

**The tool computes. The agent thinks. The human decides.**

## What it does

Eureka ingests sources (books, videos, articles, notes), extracts atomic ideas, links them by semantic similarity, and discovers non-obvious connections using embedding geometry and information theory.

- **Atoms** — single concepts written as opinionated claims
- **Molecules** — insights synthesized from 2+ atoms that say something none of them say alone
- **Discovery** — triangles (agreement across sources), V-structures (tension), and 7 other geometric methods
- **Scoring** — information theory metric (coherence × novelty × emergence), normalized 0-100

## Install

```bash
pip install git+https://github.com/arunthiru/eureka.git
```

## Quick start

```bash
# Initialize a brain
eureka init ~/brain

# Ingest a source
eureka ingest ~/Downloads/book.pdf --brain-dir ~/brain
eureka ingest https://youtube.com/watch?v=abc123 --brain-dir ~/brain

# Check brain health
eureka status ~/brain

# Discover new insights
eureka discover ~/brain

# Query the brain
eureka ask "how should I price my services" --brain-dir ~/brain

# Review pending molecules
eureka review some-molecule-slug yes --brain-dir ~/brain

# Visual dashboard
eureka serve ~/brain
# → http://localhost:8765
```

## For agents

Every command outputs JSON to stdout. Progress goes to stderr. See [AGENTS.md](AGENTS.md) for the full agent interface specification.

```json
{"ok": true, "command": "ingest", "data": {"atoms_created": 14, "source": {"title": "...", "type": "pdf"}}}
```

Exit codes: 0=success, 1=failure, 2=usage error, 3=not found, 5=conflict.

## Dashboard

`eureka serve` starts a localhost dashboard with 4 tabs:

- **Graph** — force-directed layout with node shapes (circles=atoms, triangles, V's, diamonds=molecules)
- **Search** — full-text search across all notes
- **Molecules** — browse accepted molecules with ELI5 explanations
- **Review** — accept/reject pending molecules with keyboard shortcuts (y/n)

## How it works

```
Source → Chunk → Extract Atoms → Index → Embed → Link → Discover → Score → Write Molecule → ELI5
         ~~~~~~~~~~~~LLM~~~~~~~~~~~~   ~~~~~deterministic~~~~~   ~~~~~~~~~~~LLM~~~~~~~~~~~~
```

Three steps use an LLM. Everything else is deterministic: embedding geometry, graph topology, information theory.

## License

MIT
