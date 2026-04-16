"""Tests for eureka lint — brain health checks."""

import struct
from datetime import date
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.embeddings import _deterministic_embed


def _seed_brain(tmp_path):
    """Create a brain with well-linked atoms and proper frontmatter."""
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    atoms_dir = brain_dir / "atoms"
    atoms_dir.mkdir()
    (brain_dir / "molecules").mkdir()

    atoms = {
        "barbell-strategy": {
            "title": "Barbell strategy",
            "body": "Put 90% in safe assets and 10% in high-risk bets. Avoid the middle.",
            "tags": "risk, strategy",
        },
        "skin-in-the-game": {
            "title": "Skin in the game",
            "body": "Never trust advice from someone who doesn't bear the downside of being wrong.",
            "tags": "risk, decision-making",
        },
        "antifragile-systems": {
            "title": "Antifragile systems",
            "body": "Systems that gain from disorder are antifragile. Stress makes them stronger.",
            "tags": "risk, systems",
        },
    }

    for slug, data in atoms.items():
        md = (
            "---\n"
            f"type: atom\n"
            f"tags: [{data['tags']}]\n"
            f"date: 2026-01-01\n"
            "---\n"
            f"# {data['title']}\n\n{data['body']}\n\ntags: {data['tags']}\n"
        )
        (atoms_dir / f"{slug}.md").write_text(md)

    conn = open_db(brain_dir / "brain.db")
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    from eureka.core.embeddings import ensure_embeddings
    ensure_embeddings(conn, brain_dir, embed_fn=_deterministic_embed)
    from eureka.core.linker import link_all
    link_all(conn)

    return brain_dir, conn


def _load_embeddings(conn):
    rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
    emb = {}
    for r in rows:
        dim = len(r["vector"]) // 4
        emb[r["slug"]] = list(struct.unpack(f"{dim}f", r["vector"]))
    return emb


def test_lint_clean_brain(tmp_path, monkeypatch):
    """A well-formed brain with linked atoms should have few or zero issues."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)

    from eureka.core.lint import lint
    result = lint(conn, brain_dir, embeddings=embeddings)

    # Well-linked atoms with proper frontmatter — no broken links, no missing FM
    assert result["broken_links"] == []
    assert result["missing_frontmatter"] == []
    # Summary should reflect low/zero issues
    assert result["summary"]["broken_links"] == 0
    assert result["summary"]["missing_frontmatter"] == 0
    conn.close()


def test_lint_finds_orphans(tmp_path, monkeypatch):
    """Atoms with no edges and no molecule membership appear as orphans."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)

    # Add an isolated atom with no edges
    atoms_dir = brain_dir / "atoms"
    (atoms_dir / "lonely-island.md").write_text(
        "---\ntype: atom\ntags: [isolation]\ndate: 2026-01-01\n---\n"
        "# Lonely island\n\nThis atom has no connections.\n\ntags: isolation\n"
    )
    from eureka.core.index import rebuild_index
    rebuild_index(conn, brain_dir)
    # Don't run ensure_embeddings/link_all for the new atom — it stays orphaned

    from eureka.core.lint import lint
    result = lint(conn, brain_dir, embeddings={})

    assert "lonely-island" in result["orphans"]
    assert result["summary"]["orphans"] >= 1
    conn.close()


def test_lint_finds_broken_links(tmp_path, monkeypatch):
    """Wiki-links to nonexistent slugs appear in broken_links."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)

    # Write an atom file with a broken wikilink at brain root (where lint scans)
    (brain_dir / "has-broken-link.md").write_text(
        "# Has broken link\n\nSee [[nonexistent-slug]] for more.\n\ntags: test\n"
    )

    from eureka.core.lint import lint
    result = lint(conn, brain_dir, embeddings={})

    broken_refs = [bl["broken_link"] for bl in result["broken_links"]]
    assert "nonexistent-slug" in broken_refs
    assert result["summary"]["broken_links"] >= 1
    conn.close()


def test_lint_finds_duplicates(tmp_path, monkeypatch):
    """Two atoms with identical embedding vectors appear as duplicates."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)

    # Inject two slugs with identical vectors to guarantee sim ~1.0
    vec = [1.0] * 128
    embeddings["duplicate-one"] = vec
    embeddings["duplicate-two"] = vec

    # Also insert them into the atoms table so they're real atoms
    conn.execute(
        "INSERT OR IGNORE INTO atoms (slug, title, body) VALUES (?, ?, ?)",
        ("duplicate-one", "Duplicate one", "same content"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO atoms (slug, title, body) VALUES (?, ?, ?)",
        ("duplicate-two", "Duplicate two", "same content"),
    )
    conn.commit()

    from eureka.core.lint import lint
    result = lint(conn, brain_dir, embeddings=embeddings)

    # The identical atoms should appear as a duplicate pair
    found = any(
        "duplicate-one" in (d["a"], d["b"]) and "duplicate-two" in (d["a"], d["b"])
        for d in result["duplicates"]
    )
    assert found, f"Expected duplicate pair not found. Duplicates: {result['duplicates']}"
    # Similarity should be ~1.0
    for d in result["duplicates"]:
        if "duplicate-one" in (d["a"], d["b"]):
            assert d["similarity"] > 0.95
    conn.close()


def test_lint_finds_missing_frontmatter(tmp_path, monkeypatch):
    """An atom file without --- frontmatter block appears in missing_frontmatter."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)

    # Write an atom at brain root without YAML frontmatter (no --- block)
    (brain_dir / "no-frontmatter.md").write_text(
        "# No frontmatter\n\nThis file has no YAML frontmatter at all.\n\ntags: test\n"
    )

    from eureka.core.lint import lint
    result = lint(conn, brain_dir, embeddings={})

    missing_slugs = [mf["slug"] for mf in result["missing_frontmatter"]]
    assert "no-frontmatter" in missing_slugs
    assert result["summary"]["missing_frontmatter"] >= 1
    conn.close()


def test_lint_report_written(tmp_path, monkeypatch):
    """write_report creates a dated markdown file in brain/_lint/."""
    monkeypatch.setattr("eureka.core.ask.embed_text", _deterministic_embed)
    brain_dir, conn = _seed_brain(tmp_path)
    embeddings = _load_embeddings(conn)

    from eureka.core.lint import lint, write_report
    result = lint(conn, brain_dir, embeddings=embeddings)
    report_path = write_report(result, brain_dir)

    today = date.today().isoformat()
    expected = brain_dir / "_lint" / f"{today}.md"
    assert report_path == expected
    assert expected.exists()
    content = expected.read_text()
    assert "Brain Lint" in content
    assert "Summary" in content
    conn.close()
