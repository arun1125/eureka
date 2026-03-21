"""LLM client — pluggable backends for atom extraction."""

import json
import subprocess
import sys
import urllib.request


class GeminiCLI:
    """Calls the gemini CLI as a subprocess."""

    def generate(self, prompt: str) -> str:
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


class KimiK2:
    """Calls Kimi K2.5 via the Moonshot AI API (OpenAI-compatible)."""

    def __init__(self, api_key: str, base_url: str = "https://api.moonshot.ai/v1"):
        self.api_key = api_key
        self.base_url = base_url

    def generate(self, prompt: str) -> str:
        import time
        body = json.dumps({
            "model": "kimi-k2.5",
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "disabled"},
            "max_tokens": 8192,
        }).encode()

        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=120)
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    wait = (attempt + 1) * 10
                    print(f"Rate limited, waiting {wait}s...", file=sys.stderr, flush=True)
                    time.sleep(wait)
                else:
                    raise


def get_llm():
    """Return the default LLM client. Checks env vars for config."""
    import os
    kimi_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    if kimi_key:
        return KimiK2(kimi_key)
    return GeminiCLI()
