"""eureka init — create a brain directory with auto-detected LLM."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from eureka.core.db import open_db
from eureka.core.output import emit, envelope


def _detect_llm_config() -> dict:
    """Auto-detect the best available LLM provider. No questions asked.

    Priority: claude CLI > ANTHROPIC_API_KEY > OPENAI_API_KEY > gemini CLI > None
    """
    if shutil.which("claude"):
        return {"provider": "claude-cli", "model": "haiku"}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"provider": "claude", "model": "claude-haiku-4-5-20251001"}
    if os.environ.get("OPENAI_API_KEY"):
        return {"provider": "openai", "model": "gpt-4o-mini"}
    if shutil.which("gemini"):
        return {"provider": "gemini"}
    return {}


GITIGNORE = """\
brain.db
brain.db-journal
brain.db-wal
.env
__pycache__/
*.pyc
"""


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

    # Create .gitignore
    gitignore_path = brain_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(GITIGNORE)

    # Create brain.json with auto-detected LLM
    brain_json = brain_dir / "brain.json"
    if not brain_json.exists():
        llm_config = _detect_llm_config()
        config = {"llm": llm_config, "pipeline": {}}
        brain_json.write_text(json.dumps(config, indent=2) + "\n")

    # Report what was detected
    detected = json.loads(brain_json.read_text()).get("llm", {})
    provider = detected.get("provider", "")

    result = {"brain_dir": str(brain_dir)}
    if provider:
        result["llm_provider"] = provider
        result["llm_model"] = detected.get("model", "default")
    else:
        result["llm_provider"] = None
        result["llm_warning"] = (
            "No LLM detected. Run `eureka setup` to configure one, "
            "or install Claude Code (`claude` CLI) for zero-config setup."
        )

    emit(envelope(True, "init", result))
