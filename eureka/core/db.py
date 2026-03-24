"""Database utilities."""

import sqlite3
from pathlib import Path


def open_db(db_path: Path) -> sqlite3.Connection:
    """Create/open brain.db and ensure schema exists.

    If db_path is a directory, appends 'brain.db' automatically.
    """
    db_path = Path(db_path)
    if db_path.is_dir():
        db_path = db_path / "brain.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS atoms (
            slug TEXT PRIMARY KEY,
            title TEXT,
            body TEXT,
            body_hash TEXT,
            word_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS edges (
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            similarity REAL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (source, target),
            FOREIGN KEY (source) REFERENCES atoms(slug),
            FOREIGN KEY (target) REFERENCES atoms(slug)
        );
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS note_tags (
            slug TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (slug, tag_id),
            FOREIGN KEY (slug) REFERENCES atoms(slug),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        );
        CREATE TABLE IF NOT EXISTS molecules (
            slug TEXT PRIMARY KEY,
            title TEXT,
            method TEXT,
            score REAL DEFAULT 0,
            review_status TEXT DEFAULT 'pending',
            status TEXT DEFAULT 'pending',
            eli5 TEXT,
            body TEXT,
            reviewed_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS molecule_atoms (
            molecule_slug TEXT NOT NULL,
            atom_slug TEXT NOT NULL,
            PRIMARY KEY (molecule_slug, atom_slug),
            FOREIGN KEY (molecule_slug) REFERENCES molecules(slug),
            FOREIGN KEY (atom_slug) REFERENCES atoms(slug)
        );
        CREATE TABLE IF NOT EXISTS discovery_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            params TEXT,
            candidates_found INTEGER,
            candidates_accepted INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            type TEXT NOT NULL,
            url TEXT,
            author TEXT,
            ingested_at TEXT NOT NULL,
            atom_count INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            raw_text TEXT
        );
        CREATE TABLE IF NOT EXISTS embeddings (
            slug TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            vector BLOB NOT NULL,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profile (
            key TEXT PRIMARY KEY,
            value TEXT,
            source TEXT,
            confidence REAL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            slug TEXT,
            query TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts4(slug, body, tags);
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            status TEXT DEFAULT 'ok',
            detail TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Migrate: add similarity column to edges if missing (pre-existing databases)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)").fetchall()}
    if "similarity" not in cols:
        conn.execute("ALTER TABLE edges ADD COLUMN similarity REAL")

    # Migrate: lineage tracking columns
    _migrate_lineage(conn)

    # Migrate: sync notes.tags JSON column → tags/note_tags normalized tables.
    _sync_note_tags(conn)

    conn.commit()
    return conn


def _migrate_lineage(conn: sqlite3.Connection) -> None:
    """Add lineage tracking columns to existing tables."""
    # atoms: source_id + file_hash
    cols = {r[1] for r in conn.execute("PRAGMA table_info(atoms)").fetchall()}
    if "source_id" not in cols:
        conn.execute("ALTER TABLE atoms ADD COLUMN source_id INTEGER REFERENCES sources(id)")
    if "file_hash" not in cols:
        conn.execute("ALTER TABLE atoms ADD COLUMN file_hash TEXT")

    # molecules: discovery_run_id + generation metadata
    cols = {r[1] for r in conn.execute("PRAGMA table_info(molecules)").fetchall()}
    if "discovery_run_id" not in cols:
        conn.execute("ALTER TABLE molecules ADD COLUMN discovery_run_id INTEGER REFERENCES discovery_runs(id)")
    if "candidate_score" not in cols:
        conn.execute("ALTER TABLE molecules ADD COLUMN candidate_score REAL")
    if "llm_model" not in cols:
        conn.execute("ALTER TABLE molecules ADD COLUMN llm_model TEXT")
    if "file_hash" not in cols:
        conn.execute("ALTER TABLE molecules ADD COLUMN file_hash TEXT")

    # molecule_atoms: role
    cols = {r[1] for r in conn.execute("PRAGMA table_info(molecule_atoms)").fetchall()}
    if "role" not in cols:
        conn.execute("ALTER TABLE molecule_atoms ADD COLUMN role TEXT DEFAULT 'member'")


def log_operation(conn: sqlite3.Connection, op_type: str, *,
                  status: str = "ok", detail: dict = None) -> None:
    """Log an operation to the operations table."""
    import json
    conn.execute(
        "INSERT INTO operations (type, status, detail) VALUES (?, ?, ?)",
        (op_type, status, json.dumps(detail) if detail else None),
    )


def _sync_note_tags(conn: sqlite3.Connection) -> None:
    """Populate tags/note_tags from notes.tags JSON column if they're out of sync.

    Runs on every open_db call but is fast: checks counts first, only does work
    when the notes table has tags but note_tags is empty or stale.
    """
    import json as _json

    if not _table_exists(conn, "notes"):
        return

    notes_with_tags = conn.execute(
        "SELECT count(*) FROM notes WHERE tags IS NOT NULL AND tags != '' AND tags != '[]'"
    ).fetchone()[0]
    if notes_with_tags == 0:
        return

    existing_note_tags = conn.execute("SELECT count(*) FROM note_tags").fetchone()[0]
    if existing_note_tags >= notes_with_tags:
        return  # Already in sync (or populated by rebuild_index)

    # Rebuild: clear and repopulate from JSON column
    conn.execute("DELETE FROM note_tags")
    conn.execute("DELETE FROM tags")

    rows = conn.execute("SELECT slug, tags FROM notes WHERE tags IS NOT NULL AND tags != ''").fetchall()
    for row in rows:
        try:
            tags_list = _json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
        except (ValueError, TypeError):
            continue
        if not isinstance(tags_list, list):
            continue
        for tag_name in tags_list:
            if not tag_name or not isinstance(tag_name, str):
                continue
            tag_id = ensure_tag(conn, tag_name)
            conn.execute(
                "INSERT OR IGNORE INTO note_tags (slug, tag_id) VALUES (?, ?)",
                (row["slug"], tag_id),
            )


def ensure_tag(conn: sqlite3.Connection, tag_name: str) -> int:
    """Insert tag if not exists, return tag id."""
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
    if row:
        return row["id"]
    conn.execute("INSERT INTO tags (name) VALUES (?)", (tag_name,))
    return conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()["id"]


def tag_note(conn: sqlite3.Connection, slug: str, tag_id: int) -> None:
    """Link a note to a tag (idempotent)."""
    conn.execute(
        "INSERT OR IGNORE INTO note_tags (slug, tag_id) VALUES (?, ?)",
        (slug, tag_id),
    )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


_ALLOWED_TABLES = {"atoms", "molecules", "sources", "edges", "tags", "note_tags",
                    "embeddings", "reviews", "discovery_runs", "molecule_atoms",
                    "profile", "activity", "notes"}


def _count(conn: sqlite3.Connection, table: str, column: str = None, value: str = None) -> int:
    """Count rows. Only allows whitelisted table names and parameterized WHERE."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Table {table!r} not in allowed set")
    if not _table_exists(conn, table):
        return 0
    if column and value is not None:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()[0]
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def use_notes_table(conn: sqlite3.Connection) -> bool:
    """Return True if the 'notes' table has data and 'atoms' is empty.

    SecondBrainKit stores data in a 'notes' table with a different schema.
    This helper lets all code transparently fall back to it.
    """
    atoms_count = _count(conn, "atoms")
    if atoms_count > 0:
        return False
    if _table_exists(conn, "notes"):
        return _count(conn, "notes") > 0
    return False


def atom_table(conn: sqlite3.Connection) -> str:
    """Return the table name to use for atom queries ('atoms' or 'notes')."""
    return "notes" if use_notes_table(conn) else "atoms"


def atom_title_expr(conn: sqlite3.Connection) -> str:
    """Return a SQL expression for the title column.

    The 'atoms' table has a 'title' column.  The 'notes' table does not,
    so we derive it from the slug (replace hyphens with spaces).
    """
    if use_notes_table(conn):
        return "REPLACE(slug, '-', ' ')"
    return "title"


def atom_source_expr(conn: sqlite3.Connection) -> str:
    """Return a SQL expression for the source column.

    atoms table: source_title if it exists, else NULL
    notes table: source
    """
    if use_notes_table(conn):
        return "source"
    # Check if atoms table actually has source_title column
    cols = {r[1] for r in conn.execute("PRAGMA table_info(atoms)").fetchall()}
    if "source_title" in cols:
        return "source_title"
    return "NULL"


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return brain statistics dict."""
    tbl = atom_table(conn)
    atoms = _count(conn, tbl)
    mol_total = _count(conn, "molecules")
    mol_pending = _count(conn, "molecules", "review_status", "pending")
    mol_accepted = _count(conn, "molecules", "review_status", "accepted")
    mol_rejected = _count(conn, "molecules", "review_status", "rejected")
    sources = _count(conn, "sources")
    edges = _count(conn, "edges")

    profile_entries = _count(conn, "profile")
    activity_count = _count(conn, "activity")

    return {
        "atoms": atoms,
        "molecules": {
            "total": mol_total,
            "pending": mol_pending,
            "accepted": mol_accepted,
            "rejected": mol_rejected,
        },
        "sources": sources,
        "edges": edges,
        "profile_entries": profile_entries,
        "activity_count": activity_count,
    }
