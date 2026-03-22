# Eureka: What We Learned, What We Tried, Where the Ideas Came From

Notes for the YouTube video. Everything below documents the 7-day build arc (Mar 16–22, 2026) from raw brain scripts to a full molecular note system, and the principles that drive Eureka's design.

---

## The Principles Behind Eureka

These aren't marketing bullets — they're the actual engineering constraints that shaped every decision.

### 1. Your data is yours
No hosted service. No account. No telemetry. SQLite on your machine. I don't want your data. If that means fewer users, fine.

### 2. Agent-first development
The CLI outputs structured JSON. It never calls an LLM — that's the agent's job. Any agent framework (Claude Code, OpenAI Agents SDK, LangChain, raw scripts) can orchestrate it. The tool is the computation layer; the agent is the intelligence layer.

### 3. CLIs over APIs
Every operation is a CLI command. `eureka ingest`, `eureka discover`, `eureka ask`. No REST API to maintain, no auth to configure, no server to run (dashboard is optional). CLIs compose with pipes, scripts, cron, and agents natively.

### 4. Modular — swap any LLM
Extraction, synthesis, and evaluation are LLM calls made by the agent, not the tool. Switch from Claude to Gemini to a local model — the tool doesn't care. Each piece (reader, linker, scorer, discovery) is independent.

### 5. LLM evals with tight feedback loops
Every molecule gets scored mathematically (coherence × novelty × emergence). The human reviews with Y/N/Skip. That feedback tightens the generator. Binary evals, not rubrics. The loop is: discover → score → review → learn → discover better.

### 6. Graph theory as the backbone
Your notes are a graph. Communities, bridges, missing triangles, voids — these are real algorithms running on your actual link structure, not metaphors. The graph is the primary data structure, not folders or tags.

### 7. Information theory for scoring
Conditional entropy measures genuine novelty. Synergy measures whether the combination exceeds the sum. Channel novelty prevents redundant bridges. These are mathematical, not vibes.

### 8. Linear algebra for discovery
Atoms live in 384-dimensional embedding space. Gram determinants measure volume (diversity). Orthogonal projection measures residual novelty. L-BFGS-B optimization finds optimal points in the space and snaps to real atoms.

### 9. Skills as documentation
All documentation is written as executable skill atoms — not dead README files. An agent reads the skill and knows how to use the tool. A human reads it and understands the design. Same artifact serves both.

### 10. The repo is there if you want it
Open source. Download it, fork it, ignore it. No community to manage, no Discord to moderate, no enterprise tier. The code exists because the code is useful.

---

## The Journey (Timeline)

### Phase 0: Raw Scripts (pre Mar 16)
- Brain was ~123 atoms in `brain/` — hand-written markdown files with `[[wikilinks]]`
- Python scripts (`brain_search.py`, `_graph.py`, `_embeddings.py`, etc.) bolted on one at a time
- No unified CLI, no tests, no spec — just scripts that Arun ran ad-hoc
- Search was FTS5 (SQLite full-text search) with BM25 ranking, pure stdlib

### Phase 1: Mining Sessions (Mar 16–18) — 9 sessions
- **Session 1 (Mar 16):** Added 54 atoms from 4 sources (Andy Matuschak's notes, zettelkasten.de, tweets). Reached 177 atoms.
- **Session 2 (Mar 17):** Began exploring molecule generation — the idea that combining 2–3 atoms produces a genuinely new insight (not a summary). First attempt at "collision detection" in embedding space.
- **Session 3 (Mar 17):** Louvain community detection on the link graph. First time we could see clusters of related ideas and — more importantly — the *gaps* between clusters.
- **Session 4 (Mar 17):** Built the first CLI (`brain/cli.py`). Commands: status, check, score, health, link, generate, warmth, prune.
- **Session 5 (Mar 18):** Embedding experiments. TF-IDF (pure stdlib, instant) vs QMD semantic search (~6s cold, instant warm). Decided: QMD primary, TF-IDF fallback.
- **Session 6 (Mar 18):** Molecule generation methods v1 — collisions (0.15–0.5 similarity pairs across communities), gaps (zero-bridge community pairs), random walks (biased toward community boundaries).
- **Session 7 (Mar 18):** Auto-linking overhaul. Blended three signals: semantic similarity (QMD), Jaccard structural co-linkage (0.3 weight), Adamic-Adar neighbor rarity (0.2 weight). Orphan-aware weighting.
- **Session 8 (Mar 19):** Scoring system. Atoms: frontmatter/tags/links/body/source (0–100). Molecules: atom count, cluster span, emergent vocabulary, embedding distance, incoming links, source diversity.
- **Session 9 (Mar 19):** Health metrics, pruning pipeline, dashboard visualization.

### Phase 2: SecondBrainKit Build (Mar 19)
- Formalized everything into a proper Python package with 24 commands, 9 readers, 111 tests (TDD)
- Ported Arun's live brain (269 notes) to the new tool
- Key decision: tool never calls an LLM — that's the agent's job. CLI is pure computation.

### Phase 3: Molecule Generation Deep Dive (Mar 19–20)
- 86 molecules across 8 generation methods
- 1000+ auto-generated links
- Built the "Idea Lab" dashboard (generate.html) with D3 subgraph visualization

### Phase 4: Scoring & Void Discovery (Mar 20)
- Information-theoretic scoring (conditional entropy, synergy, channel novelty)
- Void finder — the breakthrough. Instead of scoring pairs, find the *gaps* in embedding space.
- Key finding: additive weighted signals don't work (most signals saturate on diverse brains). Multiplicative scoring works.

### Phase 5: Eureka (Mar 21)
- Rebranded and rebuilt as Eureka — added server, dashboard, discovery engine, LLM integration
- Built Augustin's brain as proof: 149 atoms from 6 books + 11 YouTube videos, 120 molecules
- Pushed to GitHub

---

## Academic Disciplines & Techniques Used

### Graph Theory
| Technique | What it does in the system | Source |
|-----------|---------------------------|--------|
| **Louvain community detection** | Groups atoms into topic clusters by maximizing modularity. Used resolution=2.0 to split large clusters. | Blondel et al. 2008 — "Fast unfolding of communities in large networks" |
| **Betweenness centrality (Brandes' algorithm)** | Finds atoms that bridge between clusters — the connective tissue of the brain. O(VE). | Brandes 2001 |
| **Articulation points (Tarjan's DFS)** | Finds atoms whose removal would disconnect parts of the graph. Fragility detection. | Tarjan 1972 |
| **k-core decomposition** | Finds the densely connected core of the brain vs the periphery. | Seidman 1983 |
| **Structural holes** | Counts pairs of an atom's neighbors that aren't linked to each other — measures brokerage potential. | Burt 1992 — "Structural Holes" |
| **Missing triangle detection** | A↔B and B↔C exist but no A↔C. Each missing triangle is a molecule candidate (A and C connected through shared concept B). | Basic graph theory |
| **Adamic-Adar index** | Weights shared neighbors by rarity (1/log(degree)) — a neighbor shared with few others is more meaningful. | Adamic & Adar 2003 |
| **PageRank** | Ranks atom importance by link structure. | Brin & Page 1998 |

### Linear Algebra & Embeddings
| Technique | What it does | Source |
|-----------|-------------|--------|
| **Cosine similarity on unit-normalized vectors** | Core similarity measure between any two atoms in 384-dimensional space. | Standard NLP |
| **Gram matrix determinant (simplex volume)** | Measures how much geometric volume a set of atom vectors spans. High volume = diverse, novel combination. Low volume = redundant. | Linear algebra — Gram determinant |
| **Least-squares projection (Moore-Penrose pseudoinverse)** | Projects a molecule's embedding onto the subspace spanned by its atoms. The residual (orthogonal component) measures genuine novelty — what the molecule adds beyond its parts. | Linear algebra — orthogonal projection |
| **L-BFGS-B optimization** | Finds the optimal point in embedding space for a new molecule, then snaps to nearest real atoms. Seeded from diverse atoms per community. | Nocedal 1980 — Limited-memory BFGS |
| **BAAI/bge-small-en-v1.5 embeddings** | 384-dimensional sentence embeddings via FastEmbed. Small enough to run locally, good enough for semantic similarity. | Beijing Academy of AI |

### Information Theory
| Technique | What it does | Source |
|-----------|-------------|--------|
| **Conditional entropy** | Measures how much new information a molecule carries given its constituent atoms. Uses orthogonal projection — the residual from projecting molecule embedding onto atom subspace. | Shannon 1948 — formalized here as geometric conditional entropy |
| **Synergy** | Measures whether combining atoms produces more value than the sum of parts. Compares molecule's embedding to individual atom embeddings. | Partial Information Decomposition (Williams & Beer 2010) — simplified |
| **Channel novelty** | Measures how unique a particular bridge between two atoms is, compared to all other bridges. Prevents redundant molecules. | Information channel capacity (Shannon) |

### Physics Analogies (v2 Design)
| Analogy | Application | Source |
|---------|-------------|--------|
| **Lennard-Jones potential** | Optimal semantic distance between atoms in a molecule — too close = redundant, too far = incoherent. Sweet spot around 0.3–0.5 cosine similarity. | Molecular physics — intermolecular forces |
| **Free energy (F = U - TS)** | Molecule quality = fit (low energy, coherent) minus novelty (high entropy, surprising). Trade-off between saying something new and saying something coherent. | Thermodynamics |
| **Valence / bonding capacity** | Each atom has a "valence" — how many molecules it can meaningfully participate in. High-betweenness atoms have higher valence. | Chemistry — covalent bonding |
| **Void detection** | Semantic gaps in embedding space = "voids" where no atom exists. Midpoint between two cross-community atoms, measured by distance to nearest real atom. The bigger the void, the more unexplored the territory. | Cosmological void surveys (Hoyle & Vogeley 2004) — repurposed |

### NLP & Search
| Technique | What it does | Source |
|-----------|-------------|--------|
| **TF-IDF** | Term frequency × inverse document frequency. Pure stdlib implementation, instant. Used as fallback when embeddings unavailable. | Salton & Buckley 1988 |
| **BM25 (via FTS5)** | Probabilistic ranking function for full-text search. Built into SQLite. | Robertson et al. 1995 |
| **Semantic search (QMD/FastEmbed)** | Dense vector search. Embed query, find nearest neighbors by cosine similarity. | Modern neural IR |

### Zettelkasten / Knowledge Management
| Concept | How we used it | Source |
|---------|---------------|--------|
| **Atomic notes** | One concept per note, titled as a complete declarative phrase | Niklas Luhmann (1960s), formalized by Sönke Ahrens ("How to Take Smart Notes") |
| **Evergreen notes** | Notes written to be discovered and reused, not filed and forgotten | Andy Matuschak |
| **Dense linking over tagging** | Links between notes carry more information than shared tags | Andy Matuschak, zettelkasten.de |
| **Concept-oriented not source-oriented** | Notes organized by idea, not by where you read it | Luhmann's slip-box method |
| **Quadratic growth from linking** | N notes with rich linking → O(N²) possible connections → combinatorial idea generation | Reasonable Deviations blog |

### Learning Theory (conceptual grounding)
| Concept | Relevance | Source |
|---------|-----------|--------|
| **Hoeffding inequality** | Why learning from finite data works — bounds the gap between in-sample and out-of-sample. Justified our confidence that embeddings trained on web text transfer to personal notes. | Hoeffding 1963 |
| **VC dimension** | How complex a hypothesis set really is. Informed our choice of embedding model size (384-dim is enough). | Vapnik & Chervonenkis 1971 |
| **Bias-variance tradeoff** | Too few atoms = high bias (missing ideas). Too many = high variance (noise). Pruning manages this. | Geman et al. 1992 |

---

## What Worked

1. **Void detection** — the single best discovery tool. Finding the *gaps* in your knowledge (midpoint between two atoms where nothing exists) produces more interesting molecule candidates than any pairwise scoring method.

2. **Multiplicative scoring** — coherence × novelty × emergence. Additive weighted scores saturate on diverse brains because most signals are bimodal (present/absent). Multiplicative means one zero kills the score — which is what you want.

3. **Louvain communities as the backbone** — everything interesting happens *between* communities, not within them. Cross-community pairs, zero-bridge communities, community-boundary random walks — all the best ideas came from forcing connections across cluster boundaries.

4. **CLI never calls an LLM** — pure computation. The agent calls the LLM. This separation meant the tool was fast, testable, and model-agnostic. Any agent framework can use it.

5. **Missing triangles** — A↔B and B↔C but no A↔C is a reliable signal for "these two ideas should be connected through their shared concept." Simple graph theory, surprisingly effective.

6. **Atom quality gate** — atoms titled as complete declarative phrases ("the brain is an anticipation machine that traps itself in its own predictions") are dramatically better for embedding-based operations than topic labels ("brain prediction"). The title IS the atom's embedding anchor.

7. **ELI5 with physical metaphor** — asking the LLM to explain a molecule "like you'd explain it to a 12-year-old using a physical object they can touch" produced the best synthesis. Abstract → concrete grounding.

8. **Cosine similarity sweet spot 0.3–0.5** — too similar (>0.5) = redundant paraphrase. Too different (<0.15) = incoherent nonsense. The interesting ideas live in the Goldilocks zone. This maps directly to Lennard-Jones potential in molecular physics.

## What Failed

1. **Additive weighted scoring** — PMI, source diversity, bridge count, betweenness — we tried combining them with weights (0.4/0.3/0.2/0.1). Every combination saturated. On a diverse brain, most pairs have moderate PMI and different sources. The scores all clustered around the same value. Useless for ranking.

2. **PMI (Pointwise Mutual Information)** — bimodal distribution. Pairs either co-occur a lot (high PMI) or don't at all (PMI = 0). No useful gradient in between.

3. **Global brute-force search** — O(N²) pair enumeration works at 200 atoms but won't scale. The L-BFGS-B optimizer (find optimal point in embedding space, snap to nearest atoms) was the answer, but we only got it working for n≥3 atom combinations.

4. **TF-IDF as primary** — too keyword-dependent. "Habit loop" and "behavior change" don't overlap in terms but are semantically close. Embeddings are strictly better for discovery. TF-IDF kept as search fallback only.

5. **Top-10 linking with no threshold** — early auto-linker connected everything to its 10 nearest neighbors regardless of similarity. Created a hairball graph with meaningless edges. Switching to top-5 with min_similarity=0.65 dropped edges from 1490 → 743 and made the graph actually useful.

6. **Kimi K2.5 for molecule generation** — tried it for Auggie's brain. Quality was poor compared to Claude Haiku. "Night and day difference." The model matters for synthesis even at the smallest scale.

---

## Sources Used for Brain Content

### Books (extracted into atoms)
- **"How to Take Smart Notes"** — Sönke Ahrens (Zettelkasten method, atomic notes, writing as thinking)
- **"Antifragile"** — Nassim Taleb (barbell strategy, via negativa, skin in the game, Lindy effect, optionality)
- **"The Black Swan"** — Nassim Taleb (narrative fallacy, silent evidence, Extremistan, epistemic arrogance)
- **"Atomic Habits"** — James Clear (habit loop, identity-based habits, environment design, 1% compounding)
- **"The Inner Game of Tennis"** — Timothy Gallwey (Self 1 vs Self 2, nonjudgmental observation, awareness)
- **"Prometheus Rising"** — Robert Anton Wilson (8-circuit model, reality tunnels, imprints, metaprogramming)
- **"Reality Transurfing"** — Vadim Zeland (pendulums, excess potential, outer intention, alternatives space)
- **"Poor Charlie's Almanack"** — Charlie Munger (mental models, lollapalooza effect, inversion, circle of competence)
- **"$100M Offers"** — Alex Hormozi (value equation, starving crowd, niching, dream outcome)
- **"$100M Leads"** — Alex Hormozi (core four, volume, client-financed acquisition)
- **"Obviously Awesome"** — April Dunford (positioning, competitive alternatives, value clusters)
- **"Crystallizing Public Opinion"** — Edward Bernays (PR as engineering consent, manufactured demand)
- **"Propaganda"** — Edward Bernays (invisible government, symbols as shortcuts)
- **"Thinking in Systems"** — Donella Meadows (feedback loops, leverage points, system boundaries, eroding goals)
- **"Superforecasting"** — Philip Tetlock (calibration, foxes vs hedgehogs, outside view)
- **"Learning from Data"** — Yaser Abu-Mostafa (VC dimension, Hoeffding, bias-variance, regularization)
- **"Psycho-Cybernetics"** — Maxwell Maltz (self-image, theater of the mind, automatic mechanism)
- **"Things Hidden Since the Foundation of the World"** — René Girard (mimetic desire, scapegoat mechanism, sacred violence)

### Online Sources (scraped into atoms)

**Andy Matuschak's working notes** — the single most influential source on note design:
- Evergreen notes: https://notes.andymatuschak.org/Evergreen_notes_should_be_densely_linked
- Atomic notes: https://notes.andymatuschak.org/Evergreen_notes_should_be_atomic
- Complete phrase titles: https://notes.andymatuschak.org/Prefer_note_titles_with_complete_phrases_to_sharpen_claims
- Knowledge accretion: https://notes.andymatuschak.org/Knowledge_work_should_accrete
- Associative over hierarchical: https://notes.andymatuschak.org/Prefer_associative_ontologies_to_hierarchical_taxonomies
- Spaced repetition for inklings: https://notes.andymatuschak.org/Spaced_repetition_may_be_a_helpful_tool_to_incrementally_develop_inklings

**zettelkasten.de** — atomicity and knowledge building blocks:
- Atomicity guide: https://zettelkasten.de/atomicity/guide/

**Reasonable Deviations** — the "Molecular Notes" series that directly inspired the atoms/molecules metaphor:
- Part 1 (quadratic growth from linking): https://reasonabledeviations.com/2022/04/18/molecular-notes-part-1/
- Part 2 (concept extraction across sources): https://reasonabledeviations.com/2022/06/12/molecular-notes-part-2/
- Reading philosophy (capture → cull pipeline): https://reasonabledeviations.com/2022/01/24/reading-philosophy/

**Twitter/X threads** — agent-first engineering and skill systems:
- @kepano — evergreen notes as composable objects: https://x.com/kepano/status/1875660940760285344
- @arscontexta — skill graphs
- @tricalt — self-improving skills
- @0xSero — visual QA
- @mattpocockuk — grill-me PRD
- @varun_mathur — Autoskill

### Academic Papers (techniques, not content)
- Blondel et al. 2008 — "Fast unfolding of communities in large networks" (Louvain)
- Brandes 2001 — "A faster algorithm for betweenness centrality"
- Tarjan 1972 — "Depth-first search and linear graph algorithms" (articulation points)
- Seidman 1983 — "Network structure and minimum degree" (k-core)
- Burt 1992 — "Structural Holes: The Social Structure of Competition"
- Adamic & Adar 2003 — "Friends and neighbors on the web" (link prediction)
- Williams & Beer 2010 — "Nonnegative decomposition of multivariate information" (PID/synergy)
- Shannon 1948 — "A mathematical theory of communication"
- Hoeffding 1963 — "Probability inequalities for sums of bounded random variables"
- Vapnik & Chervonenkis 1971 — "On the uniform convergence of relative frequencies"
- Nocedal 1980 — "Updating quasi-Newton matrices with limited storage" (L-BFGS)
- Salton & Buckley 1988 — "Term-weighting approaches in automatic text retrieval" (TF-IDF)
- Robertson et al. 1995 — "Okapi at TREC-3" (BM25)
- Hoyle & Vogeley 2004 — "Voids in the PSCz survey" (void detection concept)

---

## Key Insights for the Video

1. **The architecture was invented in the 1960s.** Luhmann's Zettelkasten is the perfect agent infrastructure — atomic notes, dense linking, concept-oriented organization. He accidentally built what AI agents need 60 years before they existed.

2. **The interesting ideas live in the gaps.** Not in what you've written, but in what you *haven't* written. Void detection finds the empty space between two clusters of ideas where a new insight should exist.

3. **Your brain is a graph, and graphs have mathematics.** Community detection, missing triangles, betweenness centrality — these aren't metaphors. They're algorithms you can run on your actual notes to find connections you missed.

4. **Humans are terrible at linking.** N notes = N² possible connections. At 200 notes that's 40,000 pairs. No human evaluates all of them. The agent does, and it finds the non-obvious ones — the atoms from *different books* that say the *same thing in different language*.

5. **Molecules are not summaries.** A molecule combining "habit loop" + "mimetic desire" + "pendulums" produces a genuinely new claim: "habits spread mimetically through social pendulums, which is why environment design matters more than willpower." That insight doesn't exist in any of the source books.

6. **The Goldilocks zone of similarity (0.3–0.5 cosine) is where creativity lives.** Too similar = paraphrase. Too different = nonsense. This maps exactly to the Lennard-Jones potential from molecular physics — atoms that are too close repel, too far apart don't bond. The sweet spot is a specific, measurable distance.

7. **The tool should never call an LLM.** Pure computation (graph algorithms, embeddings, scoring) stays fast, testable, deterministic. The agent layer calls the LLM for synthesis. This separation is the key architectural insight.

8. **Quality of atom titles is everything.** "The brain is an anticipation machine that traps itself in its own predictions" embeds beautifully. "Brain stuff" doesn't. Complete declarative phrases are the atom's address in embedding space.

---

## Stats at the End

- **405 atoms** across philosophy, psychology, business, learning theory, systems thinking, PR/propaganda, investing, neuroscience
- **56 molecules** — original insights combining 2–3 atoms
- **~900 edges** in the link graph
- **8 generation methods:** triangle, bridge, walk, antipodal, analogy, centroid, interpolation, cluster-boundary
- **3 scoring systems:** lint-based (v1), information-theoretic (v1.5), multiplicative embedding-only (v2)
- **9 readers:** text, PDF, EPUB, URL, tweet, YouTube, audio (Whisper), Notion, repo
- **24 CLI commands**, 111 tests, 0 external API dependencies for core operations
