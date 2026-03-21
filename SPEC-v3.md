# Eureka — Specification v3: Thought Partner

## What Changed from v2

v2 is a pipeline tool. Ingest → Extract → Discover → Review. The user interacts through commands. The brain is a database.

v3 turns the brain into a **thought partner**. The user talks to their agent. The agent uses Eureka as its knowledge backbone. When the user thinks out loud, the brain thinks with them.

**v2: "Here are your notes on X."**
**v3: "Given who you are and what you're working through, here's what your own knowledge says — and here's where it disagrees."**

The engine from v2 doesn't change. The experience layer on top does.

---

## Core Idea

Eureka is not the conversational interface. The user's agent is (Claude, GPT, whatever). Eureka feeds the agent structured context so the agent can be a better thought partner.

```
User talks to Agent
    ↓
Agent calls eureka ask / eureka dump / eureka reflect
    ↓
Eureka searches the brain (embeddings + graph + IT scoring)
    ↓
Eureka returns structured JSON (atoms, molecules, tensions, reframes, pushback)
    ↓
Agent synthesizes a response using Eureka's output as context
    ↓
User gets a thought partner that knows their accumulated knowledge
```

Eureka never generates natural language for the user. It generates structured context for the agent. The agent does the talking.

---

## New Commands

### `eureka dump "raw text" --brain-dir DIR`

The user brain-dumps. Could be typed, dictated, voice-note-transcribed, or pasted. Raw, messy, unstructured.

**What happens:**
1. Extract atoms from the dump (same LLM step as ingest, but the source is "the user's own thinking" not a book)
2. For each extracted atom, find nearest existing atoms by embedding similarity
3. Find molecules containing those neighbors
4. Find V-structures (tensions) near the new atoms
5. Find contradictions — atoms in the brain that disagree with what was just dumped
6. Find gaps — areas where the dump touches topics the brain has little coverage on
7. Auto-link new atoms to the brain
8. Git commit

**Output:**
```json
{
    "ok": true,
    "command": "dump",
    "data": {
        "atoms_extracted": [
            {"slug": "...", "title": "..."}
        ],
        "connections": [
            {"new_atom": "...", "existing_atom": "...", "similarity": 0.78, "relationship": "supports"}
        ],
        "tensions": [
            {"new_atom": "...", "existing_atom": "...", "similarity": 0.31, "note": "These two atoms point in opposite directions"}
        ],
        "molecules_touched": [
            {"slug": "...", "eli5": "...", "relevance": "Your new idea extends this existing insight"}
        ],
        "gaps": [
            {"topic": "...", "note": "You mentioned X but the brain has almost nothing on this. Consider exploring it."}
        ],
        "pushback": [
            {"atom": "...", "challenge": "You said Y three weeks ago. This dump contradicts it. Which one do you actually believe?"}
        ]
    }
}
```

The agent takes this JSON and synthesizes a natural-language response. The user sees: "Interesting — this connects to what you learned about barbell strategy, but it contradicts what you said about focus last week. Which one do you actually believe?"

---

### `eureka reflect --brain-dir DIR`

No input. Eureka looks at the brain as a whole and generates a reflection.

**What happens:**
1. Find the user's most active topics (by recent atom creation + edge density)
2. Surface unreviewed molecules
3. Find patterns — atoms the user keeps circling back to
4. Find blind spots — topics with high internal connectivity but no cross-links
5. Compare user profile goals against brain content — where is effort going vs where the user says they want to go?

**Output:**
```json
{
    "ok": true,
    "command": "reflect",
    "data": {
        "active_topics": ["positioning", "content-strategy", "risk-management"],
        "recurring_patterns": [
            {"atom": "...", "times_referenced": 7, "note": "This keeps coming up. It might be more important than you think."}
        ],
        "blind_spots": [
            {"topic_a": "marketing", "topic_b": "psychology", "note": "These are your two biggest clusters but they barely connect. There might be gold in the gap."}
        ],
        "goal_alignment": [
            {"goal": "Build YouTube channel", "brain_coverage": "strong", "note": "14 atoms on content strategy, 8 on positioning"},
            {"goal": "Network with interesting people", "brain_coverage": "weak", "note": "2 atoms total. Your brain hasn't absorbed anything about this yet."}
        ],
        "pending_review": 5,
        "molecules_to_revisit": [
            {"slug": "...", "eli5": "...", "reason": "You accepted this 2 weeks ago. Does it still hold?"}
        ]
    }
}
```

---

### `eureka ask` (upgraded from v2)

v2 returns nearest atoms + graph neighbors + molecules + tensions.

v3 adds:
- **User profile context** — the user's goals, patterns, and values, surfaced when relevant
- **Pushback** — atoms or molecules that contradict or challenge the premise of the question
- **Reframes** — V-structures near the question, formatted as "have you considered looking at this from the angle of X?"
- **Action suggestions** — based on the user's stated goals, what should they actually DO with this knowledge?

**Additional output fields:**
```json
{
    "profile_context": {
        "relevant_goals": ["Build YouTube channel"],
        "relevant_patterns": ["You tend to over-ideate and under-execute"],
        "relevant_values": ["Authenticity over polish"]
    },
    "pushback": [
        {"atom": "...", "challenge": "Your brain says X. Your question assumes the opposite."}
    ],
    "reframes": [
        {"v_structure": {"a": "...", "b": "...", "bridge": "..."}, "reframe": "What if the real question isn't A vs B, but how C makes them both true?"}
    ],
    "action_suggestions": [
        {"suggestion": "Based on your goal to build a YouTube channel and the 3 atoms about positioning — you might want to ingest a source on LinkedIn-to-YouTube funnels. Your brain has nothing on that path."}
    ]
}
```

---

## User Profile

The user profile is a first-class part of the brain. Not metadata — atoms.

### How It Gets Built

**Step 1: Onboarding questions.** When the brain is first created (or when `eureka profile` is run), ask:
- What are you working on right now?
- What are your goals for the next 3-6 months?
- What do you keep struggling with?
- What kind of person do you want to become?
- What topics are you most interested in?

Each answer gets extracted into atoms tagged `profile`. These atoms link to everything else in the brain.

**Step 2: Continuous learning.** Every dump, every review decision, every question feeds signal:
- Dumps reveal what the user is thinking about RIGHT NOW
- Accepted molecules reveal what insights resonate
- Rejected molecules reveal what doesn't land
- Questions reveal what the user is struggling with
- Recurring themes reveal patterns the user may not see

**Step 3: Periodic check-in.** `eureka reflect` can surface: "Your profile says your goal is X. But your last 20 dumps have all been about Y. Has the goal changed, or are you avoiding it?"

### Profile Schema

```sql
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    source TEXT,          -- 'onboarding', 'inferred', 'user-stated'
    confidence REAL,      -- 0-1, how confident are we this is still true
    created_at TEXT,
    updated_at TEXT
);
```

Profile entries are also atoms — they live in `atoms/` as markdown files tagged `profile`, so they participate in linking and discovery like everything else.

---

## Brain Dump as Source Type

A brain dump is a source like any other. It gets stored in the sources table with `type = 'dump'`.

But unlike books or videos, dumps are personal. The extraction prompt is different:

```
You are extracting atomic ideas from someone's raw thoughts. This is not
a polished source — it's a brain dump. The person is thinking out loud.

Rules:
1. Extract ideas that represent genuine beliefs, plans, or realizations.
   Not filler, not hedging, not "maybe I should."
2. If the person states a goal or commitment, extract it as an atom.
3. If the person contradicts something they've said before (you'll see
   existing atoms for context), note the contradiction.
4. Title each atom as an opinionated claim — what does this person
   actually believe?
5. Tag with 'dump' plus any topic tags.
```

---

## Pushback Engine

The pushback engine is the core differentiator. It makes Eureka a thought partner instead of a search engine.

### How It Works

When `eureka ask` or `eureka dump` is called:

1. **Contradiction detection.** For each new atom or query embedding, find atoms with high *topical* similarity but low *directional* agreement. (Same neighborhood in embedding space, but the claims point in opposite directions.) This is a generalization of V-structures.

2. **Pattern detection.** Track which atoms the user references, creates, or circles back to. If the same theme appears in 3+ dumps over 2+ weeks, surface it: "You keep coming back to X."

3. **Goal-reality gap.** Compare profile goals against recent activity (dumps, ingests, questions). If the user says they want to build a YouTube channel but hasn't ingested or dumped anything about it in 3 weeks, surface that.

4. **Historical contradiction.** When a new dump contradicts a previously accepted molecule or a profile atom, flag it explicitly: "You said X on March 15. Today you said the opposite. Which one do you believe?"

### What It Returns

Pushback is always structured JSON — never generated prose. The agent decides how to deliver it. The pushback has:
- The specific atom or molecule being challenged
- The nature of the challenge (contradiction, pattern, gap, drift)
- The evidence (which atoms, when created, what was said)

---

## The LinkedIn Example

User: "I want to post on LinkedIn but I don't know how. I want to post strategically and come up with a plan."

Agent calls `eureka ask "LinkedIn content strategy" --brain-dir ~/brain`

Eureka returns:
```json
{
    "nearest": [
        {"slug": "positioning-is-context-not-messaging", "similarity": 0.74},
        {"slug": "niching-down-lets-you-charge-100x", "similarity": 0.71},
        {"slug": "vulnerability-hooks-outperform-aspirational-hooks", "similarity": 0.68}
    ],
    "graph_neighbors": [
        {"slug": "context-openers-get-10x-more-dm-replies", "via": "vulnerability-hooks", "similarity": 0.65},
        {"slug": "copying-incumbent-proof-of-work-guarantees-losing", "via": "positioning-is-context", "similarity": 0.62}
    ],
    "molecules_touched": [
        {"slug": "niche-so-hard-they-feel-seen-then-unsell-to-prove-it", "eli5": "Pick a group so specific they feel like you're reading their mind, then prove you're not just selling by walking away from bad fits."}
    ],
    "tensions": [
        {"a": "vulnerability-hooks-outperform-aspirational", "b": "premium-pricing-is-a-virtuous-cycle", "bridge": "positioning-is-context-not-messaging", "note": "Being vulnerable builds trust but premium positioning requires authority. These pull in opposite directions."}
    ],
    "profile_context": {
        "relevant_goals": ["Build YouTube channel", "Network with interesting people"],
        "relevant_patterns": ["Tends to over-ideate, under-execute"]
    },
    "pushback": [
        {"challenge": "You have 14 atoms on content strategy but zero LinkedIn-specific atoms. You're trying to strategize without domain knowledge. Consider ingesting 2-3 sources on LinkedIn specifically before planning."},
        {"challenge": "Your pattern is over-ideation. Do you actually need a strategy, or do you need to post 10 times and see what happens?"}
    ],
    "reframes": [
        {"reframe": "The tension between vulnerability and authority might be the strategy itself — alternate between the two. Your brain already knows both work."}
    ],
    "action_suggestions": [
        {"suggestion": "Ingest a source on LinkedIn content (algorithm, formats, hooks). Your brain has general content strategy but nothing platform-specific."},
        {"suggestion": "Your 'context openers' atom suggests DMs outperform public posts for networking. Maybe LinkedIn isn't about posting — it's about DMing, and posts are just the excuse."}
    ]
}
```

The agent takes all of this and says something like:

"Your brain actually knows a lot about content strategy — positioning, vulnerability hooks, niche targeting. But you have zero LinkedIn-specific knowledge. Before making a plan, ingest 2-3 sources about how LinkedIn actually works.

Also — your brain says vulnerability outperforms aspirational content, but you also believe in premium positioning. That tension might BE your strategy: alternate between raw honesty and demonstrating expertise.

One more thing: your 'context openers' atom says DMs get 10x more replies than cold outreach. Maybe LinkedIn isn't about posting at all — it's about DMing people, and the posts are just the reason to start conversations. That aligns with your goal to network with interesting people.

But honestly? You tend to over-plan. Do you need a strategy, or do you need to post 10 times and learn from what happens?"

---

## Implementation Plan

### What Already Exists (v2 — done)

- Full pipeline: init, ingest, discover, ask, review, status, serve
- Embeddings + graph + IT scoring
- Triangle + V-structure discovery
- 71 tests, all green
- Dashboard with 4 tabs
- pip-installable from GitHub

### What v3 Adds

**Phase 1: Dump**
1. `eureka dump` command — extract atoms from raw text, link to brain, find connections/tensions/gaps
2. New source type `dump` in sources table
3. Contradiction detection (topical similarity + directional disagreement)
4. Dump-specific extraction prompt

**Phase 2: Profile**
1. `eureka profile` command — onboarding questions, extract profile atoms
2. Profile table in DB
3. Profile atoms tagged and linked like regular atoms
4. Profile context injected into `ask` and `dump` outputs

**Phase 3: Pushback Engine**
1. Pattern detection — track recurring themes across dumps and questions
2. Goal-reality gap detection — compare profile goals to recent activity
3. Historical contradiction detection — new claims vs old claims
4. Pushback output in `ask` and `dump` responses

**Phase 4: Reflect**
1. `eureka reflect` command — brain-wide self-assessment
2. Active topics, recurring patterns, blind spots, goal alignment
3. Molecules to revisit (time-based re-evaluation)

**Phase 5: Enhanced Ask**
1. Profile context in ask output
2. Reframes from V-structures
3. Action suggestions based on goals + brain gaps
4. Pushback integrated into ask

**Phase 6: Multi-modal Dump**
1. Voice note transcription (whisper) as dump input
2. Image/screenshot OCR as dump input
3. Source type detection for dumps

---

## What Doesn't Change

- Eureka still outputs JSON. The agent talks, not Eureka.
- SQLite is still the source of truth.
- All scoring is still information theory (coherence × novelty × emergence).
- All discovery is still deterministic geometry. The LLM writes, it doesn't decide.
- Every brain mutation is still git-committed.
- The dashboard still works — adds a Profile tab and a Dump history tab.
- The tool computes. The agent thinks. The human decides.

---

## Non-Goals (v3)

- Eureka doesn't generate conversational responses — the agent does
- No real-time streaming — dump → process → respond
- No multi-user — one brain, one person
- No cloud — local-first, always
- No opinion — Eureka surfaces what the brain knows, including contradictions. It doesn't take sides.
