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


class OpenAICompatible:
    """Any OpenAI-compatible API (OpenAI, Ollama, OpenRouter, Together, Groq, DeepSeek, Fireworks, etc.)."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str) -> str:
        import time
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
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


class ClaudeCLI:
    """Calls claude -p as a subprocess (uses Claude Code subscription, no API key needed)."""

    def __init__(self, model: str = "haiku"):
        self.model = model

    def generate(self, prompt: str) -> str:
        # Strip env vars that cause cascade/blocking in nested claude calls
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID")}
        result = subprocess.run(
            ["claude", "-p", "--model", self.model, prompt],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode != 0:
            print(f"claude CLI error: {result.stderr[:200]}", file=sys.stderr)
            raise RuntimeError(f"claude -p failed: {result.stderr[:200]}")
        return result.stdout.strip()


def load_llm_config(brain_dir) -> dict:
    """Load the llm section from brain.json and .env from the brain directory."""
    import os
    from pathlib import Path
    if brain_dir is None:
        return {}
    brain_path = Path(brain_dir)

    # Load .env file into environment (keys written by `eureka setup`)
    env_path = brain_path / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    config_path = brain_path / "brain.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text()).get("llm", {})
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}


# Well-known OpenAI-compatible base URLs
KNOWN_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "kimi": "https://api.moonshot.ai/v1",
}


def get_llm(config: dict = None):
    """Return the LLM client.

    Args:
        config: Optional dict with 'provider', 'model', 'base_url', 'api_key' keys
                (from brain.json's "llm" section). If None, uses env vars only.
    """
    import os

    config = config or {}
    provider = config.get("provider", "").lower()
    model = config.get("model")
    base_url = config.get("base_url")
    config_key = config.get("api_key")

    claude_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    kimi_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")

    # Config-specified provider
    if provider == "claude-cli":
        return ClaudeCLI(model=model or "haiku")
    if provider == "claude":
        key = config_key or claude_key
        if key:
            return Claude(key, model=model or "claude-haiku-4-5-20251001")
    if provider == "gemini":
        return GeminiCLI()
    if provider == "openai":
        key = config_key or openai_key
        if key:
            return OpenAICompatible(key, model=model or "gpt-4o-mini", base_url=base_url or KNOWN_BASE_URLS["openai"])

    # Any known OpenAI-compatible provider
    if provider in KNOWN_BASE_URLS:
        resolved_url = base_url or KNOWN_BASE_URLS[provider]
        key = config_key or openai_key or kimi_key or ""
        # Local providers (ollama, lmstudio) don't need a key
        if provider in ("ollama", "lmstudio"):
            key = key or "not-needed"
        if key:
            return OpenAICompatible(key, model=model or "default", base_url=resolved_url)

    # Generic openai-compatible with explicit base_url
    if provider == "openai-compatible" and base_url:
        key = config_key or openai_key or ""
        return OpenAICompatible(key or "not-needed", model=model or "default", base_url=base_url)

    # Fallback: env var detection
    if claude_key:
        env_model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        return Claude(claude_key, model=model or env_model)
    if openai_key:
        return OpenAICompatible(openai_key, model=model or "gpt-4o-mini")
    if kimi_key:
        return OpenAICompatible(kimi_key, model=model or "kimi-k2.5", base_url=KNOWN_BASE_URLS["kimi"])
    return GeminiCLI()
