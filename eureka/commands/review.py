"""eureka review — accept or reject a molecule."""

import sys
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.output import emit, envelope


def run_review(slug: str, decision: str, brain_dir: str) -> None:
    from eureka.core.review import accept_molecule, reject_molecule

    brain_path = Path(brain_dir)
    conn = open_db(brain_path)

    if decision not in ("yes", "accept", "no", "reject"):
        conn.close()
        emit(envelope(False, "review", {
            "message": f"Unknown decision: {decision}. Use 'yes' or 'no'.",
            "suggestion": "eureka review <slug> yes|no --brain-dir <dir>",
        }))
        sys.exit(2)

    try:
        if decision in ("yes", "accept"):
            accept_molecule(conn, slug, brain_path)
            final_decision = "accepted"
        else:
            reject_molecule(conn, slug, brain_path)
            final_decision = "rejected"
    except Exception as e:
        conn.close()
        emit(envelope(False, "review", {
            "message": str(e),
            "suggestion": f"Check that molecule '{slug}' exists: eureka status --brain-dir {brain_dir}",
        }))
        sys.exit(3)

    conn.close()
    emit(envelope(True, "review", {"slug": slug, "decision": final_decision}))
