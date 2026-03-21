"""JSON output helpers."""

import json
import sys


def envelope(ok: bool, command: str, data: dict) -> dict:
    return {"ok": ok, "command": command, "data": data}


def emit(env: dict) -> None:
    json.dump(env, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()
