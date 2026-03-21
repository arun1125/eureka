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
    """)
    conn.commit()
    return conn


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
                    "profile", "activity"}


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


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return brain statistics dict."""
    atoms = _count(conn, "atoms")
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
