"""eureka review — accept or reject a molecule."""

from pathlib import Path

from eureka.core.db import open_db
from eureka.core.output import emit, envelope
from eureka.core.review import accept_molecule, reject_molecule


def run_review(slug: str, decision: str, brain_dir: str) -> None:
    brain_path = Path(brain_dir)
    conn = open_db(brain_path)

    if decision in ("yes", "accept"):
        accept_molecule(conn, slug, brain_path)
        final_decision = "accepted"
    elif decision in ("no", "reject"):
        reject_molecule(conn, slug, brain_path)
        final_decision = "rejected"
    else:
        conn.close()
        emit(envelope(False, "review", {"message": f"Unknown decision: {decision}. Use yes/no."}))
        return

    conn.close()
    emit(envelope(True, "review", {"slug": slug, "decision": final_decision}))
