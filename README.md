# Eureka

A CLI tool that turns your AI agent into a thought partner — by dumping raw sources into a knowledge graph of atomic ideas and synthesized insights.

You feed it everything you've read — books, papers, articles, transcripts. It extracts atomic ideas, links them by meaning, and uses graph theory and embedding geometry to find connections you missed. Not a search engine for your notes. A system that exposes you to your own ideas in combinations you wouldn't have reached alone.

**The tool computes. The agent thinks. The human decides.**

## Why this exists

The quality of your thinking is a function of the input you feed it. Read one book on habits, you get a level 2 idea. Read habits AND mimetic desire AND systems thinking — and something holds all of that at once, finding the remote associations between them — you get a level 5 idea.

No human evaluates 40,000 possible connections between 200 notes. Eureka does. It finds the ideas hiding between your ideas — the atom from Atomic Habits that connects to an atom from Thinking in Systems through a concept in Girard that none of them mention.

## What it does

- **Atoms** — single ideas extracted from your sources, written as opinionated claims ("the brain is an anticipation machine that traps itself in its own predictions")
- **Molecules** — new insights synthesized from 2-3 atoms that say something none of them say alone
- **8 Discovery Methods** — missing triangles, voids in your knowledge, random walks across topic boundaries, V-structures that surface creative tension
- **Thought Partner** — ask questions with graph-aware retrieval, brain dump raw thinking and get connections + pushback, reflect on blind spots
- **Scoring** — coherence × novelty × emergence × source diversity, normalized 0-100. One zero kills the score.

## Install

```bash
pip install git+https://github.com/arun1125/eureka.git
```

## Quick start

```bash
# Initialize a brain
eureka init ~/brain

# Set it once, never type the path again
export EUREKA_BRAIN=~/brain

# Ingest sources (PDF, EPUB, TXT)
eureka ingest ~/Downloads/book.pdf
eureka ingest ~/Downloads/notes.txt

# Check brain status
eureka status

# Discover new insights
eureka discover --count 20

# Ask a question — graph-aware retrieval, not just vector search
eureka ask "why do smart people procrastinate on important work"

# Brain dump — think out loud, get connections + tensions + pushback
eureka dump "I think niching down is overrated"

# Reflect — what's overrepresented, what's missing, where are the blind spots
eureka reflect

# Review molecules — accept, reject, or skip
eureka review some-molecule-slug yes

# Visual dashboard
eureka serve
```

All commands resolve the brain directory from `EUREKA_BRAIN`, `--brain-dir`, or a positional argument — in that order.

## LLM Configuration

Eureka needs an LLM for three things: extracting atoms from sources, writing molecule synthesis, and answering questions. Everything else — linking, scoring, discovery, graph analysis — is deterministic math. We recommend Claude for the writing — it produces noticeably better atom extraction and molecule synthesis than alternatives we tested. You can use any provider, but the quality difference is real.

Configure your LLM in `brain.json` (created by `eureka init`):

```json
{
  "llm": {
    "provider": "claude",
    "model": "claude-haiku-4-5-20251001"
  }
}
```

Set your API key as an environment variable:

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Supported providers:

| Provider | `brain.json` provider | API key env var | Notes |
|----------|-----------------------|-----------------|-------|
| Claude | `"claude"` | `ANTHROPIC_API_KEY` | Recommended. Haiku is fast and cheap. Set `"model"` to `"claude-sonnet-4-6-20250514"` for important work. |
| Kimi K2.5 | `"kimi"` | `KIMI_API_KEY` | Free tier available via Moonshot AI. |
| Gemini CLI | `"gemini"` | _(none — uses `gemini` CLI on PATH)_ | Free fallback. Quality varies. |

The `brain.json` config is always local to your brain directory — each brain can use a different model.

## How `ask` is different from RAG

RAG embeds your question, finds the 10 nearest chunks, and summarizes them back at you. You get your own notes reworded.

Eureka's `ask` walks the link graph — not just vector similarity. It starts from the nearest atoms, follows edges into adjacent topic clusters, surfaces pre-synthesized molecules, and finds tensions (V-structures where two ideas disagree through a shared connector). The result includes ideas from books and domains that are semantically distant from your question but structurally connected through the graph.

RAG stays in the neighborhood. The graph crosses into territory you forgot was relevant.

## For agents

Every command outputs JSON to stdout. Progress goes to stderr. See [AGENTS.md](AGENTS.md) for the full agent interface.

```json
{"ok": true, "command": "ask", "data": {"nearest": [...], "tensions": [...], "profile_context": [...], "reframes": [...], "pushback": [...]}}
```

Exit codes: 0=success, 1=failure, 2=usage error, 3=not found, 5=conflict.

## Modular by design

Every piece is independent. Swap the reader (PDF, EPUB, TXT — add your own). Swap the LLM (Claude, Kimi, Gemini, local). Swap the scorer. The CLI is the orchestration layer, not a monolith. Fork it, mod it, plug in your own discovery methods.

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
