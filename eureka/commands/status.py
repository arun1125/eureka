"""eureka status — return brain stats as JSON."""

import sys
from pathlib import Path

from eureka.core.db import open_db, get_stats
from eureka.core.output import emit, envelope


def run_status(brain_dir_path: str) -> None:
    brain_dir = Path(brain_dir_path)

    if not brain_dir.exists() or not (brain_dir / "brain.db").exists():
        out = {"ok": False, "command": "status", "errors": [f"Brain not found: {brain_dir}"]}
        import json
        json.dump(out, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()
        sys.exit(3)

    conn = open_db(brain_dir / "brain.db")
    stats = get_stats(conn)
    conn.close()

    emit(envelope(True, "status", stats))
