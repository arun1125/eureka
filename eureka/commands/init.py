"""eureka init — create a brain directory."""

import json
import subprocess
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.output import emit, envelope

DEFAULT_CONFIG = {
    "llm": {
        "provider": "claude",
        "model": "claude-haiku-4-5-20251001",
    },
    "pipeline": {},
}


def run_init(brain_dir_path: str) -> None:
    brain_dir = Path(brain_dir_path)
    brain_dir.mkdir(parents=True, exist_ok=True)
    (brain_dir / "atoms").mkdir(exist_ok=True)
    (brain_dir / "molecules").mkdir(exist_ok=True)
    open_db(brain_dir / "brain.db")

    # Initialize git repo
    if not (brain_dir / ".git").exists():
        subprocess.run(
            ["git", "init"],
            cwd=str(brain_dir),
            capture_output=True,
        )

    # Create brain.json config
    brain_json = brain_dir / "brain.json"
    if not brain_json.exists():
        brain_json.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")

    emit(envelope(True, "init", {"brain_dir": str(brain_dir)}))
