"""LLM client — wraps gemini CLI for atom extraction."""

import subprocess
import sys


class GeminiCLI:
    """Calls the gemini CLI as a subprocess."""

    def generate(self, prompt: str) -> str:
        """Send prompt to gemini CLI, return response text."""
        result = subprocess.run(
            ["gemini"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"gemini error: {result.stderr}", file=sys.stderr)
            raise RuntimeError(f"gemini CLI failed: {result.stderr[:200]}")
        return result.stdout.strip()


def get_llm():
    """Return the default LLM client."""
    return GeminiCLI()
