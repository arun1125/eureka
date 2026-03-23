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
2. Run `eureka setup` — it asks subscription vs API tokens, configures everything
3. Tell it to ingest your sources (books, articles, transcripts, whatever)
4. Talk to the agent — ask questions, brain dump, get pushback and connections
5. Browse the dashboard when you want a visual view
6. The agent handles discovery, scoring, and maintenance in the background

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

# Configure LLM provider (interactive)
eureka setup --brain-dir ~/brain

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

## Setup

Eureka needs an LLM for three things: extracting atoms from sources, writing molecule synthesis, and answering questions. Everything else — linking, scoring, discovery, graph analysis — is deterministic math.

### Interactive setup (humans)

```bash
eureka init ~/brain
eureka setup --brain-dir ~/brain
```

The setup wizard walks you through provider selection, model choice, and API key entry, then tests the connection.

### Non-interactive setup (agents)

```bash
eureka setup-instructions                    # Returns JSON with all options
eureka setup --brain-dir ~/brain --provider claude-cli --model sonnet
```

Agents should call `setup-instructions` first to get the full provider list, ask the user what they want, then run `setup` with the answer. See [AGENTS.md](AGENTS.md) for the complete agent onboarding flow.

### Providers

| Provider | `--provider` | API key | Notes |
|----------|-------------|---------|-------|
| Claude Code subscription | `claude-cli` | None needed | Uses `claude -p`. Zero extra cost on Max/Pro. |
| Claude API | `claude` | `ANTHROPIC_API_KEY` | Direct Anthropic API. Haiku is fast and cheap. |
| OpenAI | `openai` | `OPENAI_API_KEY` | GPT-4o, GPT-4.1, etc. |
| Gemini CLI | `gemini` | None needed | Free tier. Uses `gemini` CLI on PATH. |
| Ollama | `ollama` | None needed | Local models. Free, private, offline. |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | 200+ models via openrouter.ai. |
| Together AI | `together` | `TOGETHER_API_KEY` | Fast open-source models. |
| Groq | `groq` | `GROQ_API_KEY` | Ultra-fast inference. Free tier. |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | Very cheap. |
| Any OpenAI-compatible | `openai-compatible` | Varies | Pass `--base-url`. Works with LM Studio, vLLM, Fireworks, etc. |

### Examples

```bash
# Claude Max subscriber — no key, no cost
eureka setup --brain-dir ~/brain --provider claude-cli --model sonnet

# OpenAI API
eureka setup --brain-dir ~/brain --provider openai --model gpt-4o-mini --api-key sk-xxx

# Ollama (local, free)
eureka setup --brain-dir ~/brain --provider ollama --model llama3.1

# Groq (fast, free tier)
eureka setup --brain-dir ~/brain --provider groq --api-key gsk_xxx

# Custom endpoint
eureka setup --brain-dir ~/brain --provider openai-compatible \
  --base-url https://api.example.com/v1 --model my-model --api-key xxx
```

Setup writes `brain.json` and optionally `.env` in the brain directory. The config is loaded automatically by all commands.

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

Every piece is independent. Swap the reader (PDF, EPUB, TXT — add your own). Swap the LLM (10 providers out of the box, or any OpenAI-compatible endpoint). Swap the scorer. The CLI is the orchestration layer, not a monolith.

## License

MIT
