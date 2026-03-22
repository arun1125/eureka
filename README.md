# Eureka

A CLI tool designed for AI agents to manage your second brain. You don't type these commands — your agent does.

You give your agent access to eureka. It ingests your sources, extracts atomic ideas, links them by meaning, discovers connections you missed, and synthesizes new insights. Then you talk to the agent about what it found — it can discuss, challenge, and build on the ideas using the full graph as context. The dashboard is there when you want to browse visually.

**The agent operates. The agent synthesizes. The agent discusses. You think.**

## Why this exists

No human evaluates 40,000 possible connections between 200 notes. No human should be typing `eureka discover --method void --count 20` into a terminal. Your agent does that. Then you ask it "what did you find?" and it walks you through the interesting connections, pushes back on your assumptions, and helps you think through the implications.

The quality of your thinking is a function of the input you feed it. Read one book on habits, you get a level 2 idea. Read habits AND mimetic desire AND systems thinking — and something holds all of that at once, finding the remote associations between them — you get a level 5 idea.

Eureka finds the ideas hiding between your ideas.

## How you actually use this

1. Give your agent access to the `eureka` CLI
2. Tell it to ingest your sources (books, articles, transcripts, whatever)
3. Talk to the agent — ask questions, brain dump, get pushback and connections
4. Browse the dashboard when you want a visual view
5. The agent handles discovery, scoring, and maintenance in the background

The dashboard has 4 tabs:
- **Graph** — force-directed layout of your knowledge, community coloring, click to explore
- **Search** — text search and tag filters
- **Molecules** — synthesized insights scored by coherence × novelty × emergence
- **Review** — three-way triage: "I know this" / "New & interesting" / "Doesn't excite me"

## For agents (this is the primary interface)

Every command outputs JSON to stdout. Progress goes to stderr. See [AGENTS.md](AGENTS.md) for the full agent interface.

```json
{"ok": true, "command": "ask", "data": {"nearest": [...], "tensions": [...], "profile_context": [...], "reframes": [...], "pushback": [...]}}
```

Exit codes: 0=success, 1=failure, 2=usage error, 3=not found, 5=conflict.

### Core commands

```bash
# Initialize a brain
eureka init ~/brain

# Set it once
export EUREKA_BRAIN=~/brain

# Ingest sources (PDF, EPUB, TXT)
eureka ingest ~/Downloads/book.pdf

# Check brain status
eureka status

# Discover new insights
eureka discover --count 20

# Ask a question — graph-aware retrieval, not just vector search
eureka ask "why do smart people procrastinate on important work"

# Brain dump — think out loud, get connections + tensions + pushback
eureka dump "I think niching down is overrated"

# Reflect — what's overrepresented, what's missing, blind spots
eureka reflect

# Review molecules
eureka review some-molecule-slug yes

# Start the dashboard
eureka serve
```

## What it does

- **Atoms** — single ideas extracted from your sources, written as opinionated claims
- **Molecules** — new insights synthesized from 2-3 atoms that say something none of them say alone
- **8 Discovery Methods** — missing triangles, voids, random walks, V-structures, bridges, antipodal pairs, cluster boundaries, residuals
- **Thought Partner** — ask questions with graph-aware retrieval, brain dump raw thinking, reflect on blind spots
- **Scoring** — coherence × novelty × emergence × source diversity, normalized 0-100

## How `ask` is different from RAG

RAG embeds your question, finds the 10 nearest chunks, and summarizes them back at you. You get your own notes reworded.

Eureka's `ask` walks the link graph — not just vector similarity. It starts from the nearest atoms, follows edges into adjacent topic clusters, surfaces pre-synthesized molecules, and finds tensions (V-structures where two ideas disagree through a shared connector). The result includes ideas from domains that are semantically distant from your question but structurally connected through the graph.

RAG stays in the neighborhood. The graph crosses into territory you forgot was relevant.

## Install

```bash
pip install git+https://github.com/arun1125/eureka.git
```

## LLM Configuration

Eureka needs an LLM for three things: extracting atoms from sources, writing molecule synthesis, and answering questions. Everything else — linking, scoring, discovery, graph analysis — is deterministic math.

Configure in `brain.json` (created by `eureka init`):

```json
{
  "llm": {
    "provider": "claude",
    "model": "claude-haiku-4-5-20251001"
  }
}
```

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

| Provider | Config | API key env var | Notes |
|----------|----|-----------------|-------|
| Claude | `"claude"` | `ANTHROPIC_API_KEY` | Recommended. Haiku is fast and cheap. |
| Kimi K2.5 | `"kimi"` | `KIMI_API_KEY` | Free tier available. |
| Gemini CLI | `"gemini"` | _(uses `gemini` CLI)_ | Free fallback. Quality varies. |

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

## Modular by design

Every piece is independent. Swap the reader (PDF, EPUB, TXT — add your own). Swap the LLM (Claude, Kimi, Gemini, local). Swap the scorer. The CLI is the orchestration layer, not a monolith.

## License

MIT
