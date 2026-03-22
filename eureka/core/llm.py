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


class Claude:
    """Calls Claude via the Anthropic Messages API (stdlib only)."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read().decode())
        return data["content"][0]["text"].strip()


def load_llm_config(brain_dir) -> dict:
    """Load the llm section from brain.json in the given brain directory."""
    from pathlib import Path
    if brain_dir is None:
        return {}
    config_path = Path(brain_dir) / "brain.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text()).get("llm", {})
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}


def get_llm(config: dict = None):
    """Return the LLM client.

    Args:
        config: Optional dict with 'provider' and 'model' keys
                (from brain.json's "llm" section). If None, uses env vars only.
    """
    import os

    config = config or {}
    provider = config.get("provider", "").lower()
    model = config.get("model")

    claude_key = os.environ.get("ANTHROPIC_API_KEY")
    kimi_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")

    # Config-specified provider
    if provider == "claude" and claude_key:
        return Claude(claude_key, model=model or "claude-haiku-4-5-20251001")
    if provider == "kimi" and kimi_key:
        return KimiK2(kimi_key)
    if provider == "gemini":
        return GeminiCLI()

    # Fallback: env var detection
    if claude_key:
        env_model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        return Claude(claude_key, model=model or env_model)
    if kimi_key:
        return KimiK2(kimi_key)
    return GeminiCLI()
