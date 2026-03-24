# Changelog

## 0.3.1 — Hardening

Addresses community feedback on error handling, data integrity, and thread safety.

### Fixed
- **LLM extraction failures no longer cause silent data loss.** If the LLM fails during `ingest`, the source row is rolled back so re-ingest works cleanly. Previously, a failed extraction left an orphaned source with zero atoms.
- **`extractor.extract_atoms()` now wraps LLM calls in try/except** and raises `RuntimeError` with context instead of letting raw exceptions propagate.
- **`_generate_title()` logs errors** instead of bare `except: pass`.
- **`discover` command logs which molecule failed** when LLM errors occur mid-run.
- **`--count abc` and `--port abc` no longer crash with raw Python tracebacks.** CLI validates integer args and emits proper JSON error envelopes.

### Added
- **`db.transaction()` context manager** — commits on success, rolls back on error. Used by `rebuild_index`, `link_all`, and `ensure_embeddings` (batch path).
- **Cross-method deduplication in `discover_all()`** — if two discovery methods find the same atom combination, only the first is kept instead of scoring both.
- **`threading.Lock` guards** on embedding module globals (`_backend`, `_fastembed_model`). Prevents race conditions when the server handles concurrent requests.

### Remaining (tracked for future sessions)
- CLI should migrate from manual `sys.argv` to click/argparse
- Hardcoded similarity thresholds (0.4, 0.65, 0.75, 0.85) should be configurable
- Scorer source_diversity placeholder, emergence formula instability
- Void interpolation uses Euclidean midpoint in cosine space
- FTS table is populated but never queried (server falls back to LIKE)
- URLReader and YouTubeReader still raise NotImplementedError
- No structured logging (Python `logging` module)
- No schema versioning (migrations rely on column-existence checks)
- No end-to-end integration tests
- Dashboard has no live updates (manual refresh required)
