# Eureka v3 — Implementation Plan (Thought Partner)

Tracer-bullet vertical slices on top of the existing v2 engine (71 tests, all green). Each slice touches DB → core → CLI → test and is demoable on its own. TDD per slice: write one test → make it pass → repeat.

v2 is the engine. v3 is the experience layer.

---

## Slice 11: DB Schema + Activity Log

**Demo:** `eureka status` shows profile count and activity count.

| Layer | What |
|-------|------|
| DB | Add `profile` table (key, value, source, confidence, created_at, updated_at). Add `activity` table (id, type, slug, query, timestamp). Update `get_stats()` to include profile/activity counts. |
| Core | `db.py` — new tables in schema. `activity.py` — `log_activity(conn, type, slug=None, query=None)` writes to activity table. |
| CLI | `eureka status` now shows `profile_entries` and `activity_count` in output. |
| Test | `test_db_v3.py` — profile table exists, activity table exists. `test_activity.py` — log_activity writes row, activity has correct timestamp. |

**Exit criteria:** Both tables exist. Activity logging works. Status includes new counts. No v2 tests broken.

---

## Slice 12: Dump — Extract + Connect

**Demo:** `eureka dump "I think niching down is overrated" --brain-dir ~/brain` → extracts atoms, finds connections to existing brain, returns JSON envelope.

| Layer | What |
|-------|------|
| DB | Source row with `type = 'dump'`. New atoms in atoms table. Edges created. Activity logged. |
| Core | `dump.py` — dump-specific extraction prompt, extract atoms, embed, link to existing brain, find nearest existing atoms + molecules touched. Return structured data. |
| CLI | `eureka dump "text" [--brain-dir DIR]` — full dump pipeline. |
| Test | `test_dump.py` — mock LLM, dump creates source row with type='dump', atoms extracted, connections found, JSON envelope correct shape. |

**Exit criteria:** Dump extracts atoms, links them, finds connections. Source stored as type='dump'. Activity logged. JSON output matches spec shape.

---

## Slice 13: Dump — Tensions + Gaps

**Demo:** Dump something that contradicts an existing atom → tensions array is populated. Dump about an uncovered topic → gaps array is populated.

| Layer | What |
|-------|------|
| Core | `pushback.py` — `find_contradictions(new_embeddings, all_embeddings, conn)` finds topically similar but directionally opposed atoms. `find_gaps(new_embeddings, all_embeddings, tag_counts)` finds topics with low coverage near the dump. |
| CLI | `eureka dump` output now includes `tensions` and `gaps` arrays. |
| Test | `test_pushback.py` — seeded brain with known contradiction, dump triggers it. Seeded brain with sparse topic, dump near it surfaces gap. |

**Exit criteria:** Contradictions detected between new and existing atoms. Gaps detected when dump touches sparse topics. Both appear in dump output.

---

## Slice 14: Profile — Interview + Extract

**Demo:** `eureka profile --brain-dir ~/brain` → returns structured questions. `eureka profile --answers "I'm building a YouTube channel about AI..." --brain-dir ~/brain` → extracts profile atoms, links to brain, returns what was learned.

| Layer | What |
|-------|------|
| DB | Profile rows created (key, value, source='onboarding', confidence=1.0). Profile atoms written to atoms/ tagged `profile`. Source row with `type = 'profile'`. Activity logged. |
| Core | `profile.py` — `get_questions()` → list of onboarding questions. `process_answers(conn, brain_dir, answers_text, llm)` → extract profile atoms from answers using profile-specific prompt, embed, link to brain, store in profile table + atoms/ dir. `get_profile(conn)` → all entries. `get_relevant_profile(conn, embeddings, query_embedding)` → entries near a query by similarity. |
| CLI | `eureka profile [--answers TEXT] [--brain-dir DIR]`. No args → returns questions. With --answers → processes and returns extracted profile. |
| Test | `test_profile.py` — get_questions returns 5 questions, process_answers with mock LLM creates profile rows + atom files tagged 'profile', profile atoms participate in linking, get_relevant_profile filters by similarity threshold. |

**Exit criteria:** Interview questions returned. Answers extracted into profile atoms that are real atoms (tagged, embedded, linked). Profile entries retrievable by key or by semantic proximity to a query.

---

## Slice 15: Profile — Inject into Ask + Dump

**Demo:** `eureka ask "how should I price" --brain-dir ~/brain` → output includes `profile_context` with relevant goals and patterns.

| Layer | What |
|-------|------|
| Core | `ask.py` — after finding nearest atoms, also call `get_relevant_profile()` to find profile entries near the query. Add `profile_context` to output. `dump.py` — same injection. |
| CLI | Both `ask` and `dump` output now include `profile_context`. |
| Test | `test_ask_v3.py` — seeded brain with profile entries, ask returns profile_context. `test_dump_profile.py` — dump output includes profile_context. |

**Exit criteria:** Ask and dump both surface relevant profile context. Irrelevant profile entries are NOT surfaced (similarity threshold).

---

## Slice 16: Pushback Engine — Patterns + Goal Gaps

**Demo:** After 3+ dumps on the same topic, `eureka dump` surfaces a pattern. Profile goal with no recent activity surfaces a gap.

| Layer | What |
|-------|------|
| DB | Activity table queried for recurring themes. Profile goals queried against recent activity. |
| Core | `pushback.py` — add `detect_patterns(conn, new_atoms)` (same topic in 3+ activities over 2+ weeks). Add `detect_goal_gaps(conn, profile)` (goals with no matching recent activity). |
| CLI | `eureka dump` output includes `pushback` array with pattern and gap entries. |
| Test | `test_patterns.py` — seed 3+ activities on same topic, new dump triggers pattern detection. `test_goal_gaps.py` — profile goal with no recent matching activity detected. |

**Exit criteria:** Recurring patterns surfaced. Goal-reality gaps detected. Both appear as pushback with type labels (pattern, gap).

---

## Slice 17: Pushback Engine — Historical Contradictions

**Demo:** Dump contradicts a previously accepted molecule → pushback includes the specific molecule, when it was accepted, and the contradiction.

| Layer | What |
|-------|------|
| Core | `pushback.py` — add `detect_historical_contradictions(conn, new_embeddings, all_embeddings)`. Checks new atoms against accepted molecules and profile atoms, not just regular atoms. Includes timestamp of original. |
| CLI | `eureka dump` pushback array includes historical contradiction entries with evidence. |
| Test | `test_historical_contradictions.py` — accepted molecule that new dump contradicts is surfaced with date and slug. |

**Exit criteria:** New claims checked against accepted molecules and profile atoms. Contradictions include specific evidence (slug, date, claim).

---

## Slice 18: Reflect

**Demo:** `eureka reflect --brain-dir ~/brain` → JSON with active topics, recurring patterns, blind spots, goal alignment, pending review count, molecules to revisit.

| Layer | What |
|-------|------|
| Core | `reflect.py` — `reflect(conn, brain_dir)`. Queries: recent atoms by created_at + edge density → active topics. Activity table → recurring patterns. Community detection + cross-community edge count → blind spots. Profile goals vs recent activity → goal alignment. Molecules with reviewed_at > 2 weeks ago → revisit candidates. |
| CLI | `eureka reflect [--brain-dir DIR]` |
| Test | `test_reflect.py` — seeded brain returns active topics, blind spots detected between disconnected communities, goal alignment compares profile to activity, pending review count correct. |

**Exit criteria:** All 6 output fields populated from real data. No LLM calls — pure computation. Activity logged.

---

## Slice 19: Enhanced Ask — Reframes + Actions

**Demo:** `eureka ask "should I niche down or stay broad"` → includes reframes from V-structures and action suggestions from goals + gaps.

| Layer | What |
|-------|------|
| Core | `ask.py` — after finding V-structures near the query, format them as reframes. After finding profile goals, combine with brain gap analysis to suggest actions. Pushback integrated (contradictions between query premise and brain content). |
| CLI | `eureka ask` output now includes `reframes`, `action_suggestions`, and `pushback` arrays alongside existing fields. |
| Test | `test_ask_enhanced.py` — V-structure near query becomes reframe. Profile goal + brain gap → action suggestion. Query contradicting brain content → pushback. |

**Exit criteria:** Ask returns all v3 fields. Reframes sourced from V-structures. Actions grounded in profile + gaps. Pushback grounded in contradictions.

---

## Slice 20: Dashboard — Profile + Dump Tabs

**Demo:** Dashboard has Profile tab showing goals/patterns/values. Dump History tab showing recent dumps with connections.

| Layer | What |
|-------|------|
| API | `GET /api/profile` → profile entries. `GET /api/activity?type=dump` → recent dumps with atom counts. `GET /api/reflect` → reflect output. |
| Frontend | Profile tab: editable key-value list, confidence badges, source labels. Dump History tab: timeline of dumps with extracted atom count, top connection, top tension. Reflect tab (or section): active topics, blind spots, goal alignment. |
| Test | `test_server_v3.py` — new endpoints return correct JSON shapes. |

**Exit criteria:** Profile viewable and editable from dashboard. Dump history browseable. Reflect data visible.

---

## Slice Order & Dependencies

```
v2 (71 tests green) ─── All slices start here
        │
        ▼
Slice 11 (DB + activity) ──→ Slice 12 (dump extract) ──→ Slice 13 (tensions + gaps)
        │                                                         │
        ▼                                                         ▼
Slice 14 (profile CRUD) ──→ Slice 15 (inject profile) ──→ Slice 16 (patterns + gaps)
                                                                  │
                                                                  ▼
                                                          Slice 17 (historical contradictions)
                                                                  │
                                        ┌─────────────────────────┤
                                        ▼                         ▼
                                Slice 18 (reflect)     Slice 19 (enhanced ask)
                                        │                         │
                                        └────────────┬────────────┘
                                                     ▼
                                            Slice 20 (dashboard)
```

Slices 11-12 and 14 can run in parallel (dump doesn't need profile, profile doesn't need dump).
Slice 13 needs 12. Slice 15 needs 14. Slice 16 needs 11+15. Slice 17 needs 13+16.
Slices 18 and 19 are independent after 17. Slice 20 needs everything.

## TDD Protocol (per slice)

Same as v2:
1. Pick ONE behavior from the slice
2. Write a test that fails (RED)
3. Ralph subagent makes it pass (GREEN)
4. Repeat for next behavior
5. Never write tests for internal implementation — test through public interfaces
6. Run full suite after each slice to catch regressions

## Design-an-Interface Checkpoints

- **Before Slice 13:** Pushback interface — how contradiction/gap/pattern detectors plug in and compose
- **Before Slice 18:** Reflect output — what the agent actually needs to synthesize a useful reflection
