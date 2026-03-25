"""eureka setup — interactive LLM provider configuration.

Walks the user (or their agent) through choosing an LLM backend
and writes the result to brain.json.
"""

import json
import sys
from pathlib import Path

from eureka.core.output import emit, envelope


# ── Provider specs ──────────────────────────────────────────────

PROVIDERS = {
    "claude-cli": {
        "name": "Claude Code CLI (subscription)",
        "description": "Uses your Claude Code / Claude Max subscription via `claude -p`. No API key needed.",
        "requires_key": False,
        "env_var": None,
        "default_model": "sonnet",
        "models": ["haiku", "sonnet", "opus"],
        "needs_base_url": False,
    },
    "claude": {
        "name": "Claude API (Anthropic)",
        "description": "Direct Anthropic API calls. Requires ANTHROPIC_API_KEY. Pay-per-token.",
        "requires_key": True,
        "env_var": "ANTHROPIC_API_KEY",
        "default_model": "claude-haiku-4-5-20251001",
        "models": [
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-6-20250514",
            "claude-opus-4-6-20250414",
        ],
        "needs_base_url": False,
    },
    "gemini": {
        "name": "Gemini CLI",
        "description": "Uses the `gemini` CLI on your PATH. Free tier available.",
        "requires_key": False,
        "env_var": None,
        "default_model": None,
        "models": [],
        "needs_base_url": False,
    },
    "openai": {
        "name": "OpenAI API",
        "description": "Direct OpenAI API. Requires OPENAI_API_KEY.",
        "requires_key": True,
        "env_var": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o3-mini"],
        "needs_base_url": False,
    },
    "openrouter": {
        "name": "OpenRouter",
        "description": "Access 200+ models via openrouter.ai. Requires OPENROUTER_API_KEY.",
        "requires_key": True,
        "env_var": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-haiku",
        "models": [],
        "needs_base_url": False,
    },
    "ollama": {
        "name": "Ollama (local)",
        "description": "Local models via Ollama. No API key. Must have `ollama` running.",
        "requires_key": False,
        "env_var": None,
        "default_model": "llama3.1",
        "models": [],
        "needs_base_url": False,
    },
    "openai-compatible": {
        "name": "Any OpenAI-compatible API",
        "description": "Works with Together, Groq, DeepSeek, Fireworks, LM Studio, or any OpenAI-compatible endpoint.",
        "requires_key": True,
        "env_var": "OPENAI_API_KEY",
        "default_model": None,
        "models": [],
        "needs_base_url": True,
    },
}

# Well-known shortcuts that map to openai-compatible with a preset base_url
SHORTCUTS = {
    "together": {"base_url": "https://api.together.xyz/v1", "env_var": "TOGETHER_API_KEY", "default_model": "meta-llama/Llama-3.1-8B-Instruct-Turbo"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "env_var": "GROQ_API_KEY", "default_model": "llama-3.1-8b-instant"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "env_var": "DEEPSEEK_API_KEY", "default_model": "deepseek-chat"},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1", "env_var": "FIREWORKS_API_KEY", "default_model": "accounts/fireworks/models/llama-v3p1-8b-instruct"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "env_var": None, "default_model": "default"},
    "kimi": {"base_url": "https://api.moonshot.ai/v1", "env_var": "MOONSHOT_API_KEY", "default_model": "kimi-k2.5"},
}


# ── Non-interactive mode (for agents) ──────────────────────────

def run_setup_noninteractive(brain_dir: str, provider: str, model: str = None,
                              api_key: str = None, base_url: str = None) -> None:
    """Configure LLM provider without prompts. For agent use.

    Args:
        brain_dir: Path to brain directory
        provider: One of the PROVIDERS keys, or a SHORTCUTS key, or "openai-compatible"
        model: Optional model override
        api_key: Optional API key (written to .env in brain dir)
        base_url: Required for openai-compatible, optional override for others
    """
    brain_path = Path(brain_dir)

    # Resolve shortcuts (together, groq, deepseek, etc.) to openai-compatible
    shortcut = SHORTCUTS.get(provider)
    if shortcut:
        base_url = base_url or shortcut["base_url"]
        model = model or shortcut["default_model"]
        env_var = shortcut["env_var"]
        resolved_provider = provider  # keep the name for config
    elif provider in PROVIDERS:
        spec = PROVIDERS[provider]
        env_var = spec["env_var"]
        resolved_provider = provider
        model = model or spec["default_model"]
    else:
        all_valid = list(PROVIDERS.keys()) + list(SHORTCUTS.keys())
        emit(envelope(False, "setup", {
            "message": f"Unknown provider: {provider}",
            "valid_providers": all_valid,
        }))
        sys.exit(1)

    # Validate key requirement
    needs_key = shortcut is not None or (provider in PROVIDERS and PROVIDERS[provider]["requires_key"])
    if needs_key and not api_key:
        import os
        if env_var and not os.environ.get(env_var, ""):
            emit(envelope(False, "setup", {
                "message": f"Provider '{provider}' requires an API key.",
                "env_var": env_var,
                "suggestion": f"Pass --api-key or set {env_var} in your environment.",
            }))
            sys.exit(1)

    # Validate base_url for openai-compatible
    if provider == "openai-compatible" and not base_url:
        emit(envelope(False, "setup", {
            "message": "openai-compatible requires --base-url.",
            "suggestion": "Pass --base-url https://your-api.com/v1",
        }))
        sys.exit(1)

    # Write brain.json (never store API keys here — they go in .env only)
    config = _load_or_create_config(brain_path)
    config["llm"] = {"provider": resolved_provider}
    if model:
        config["llm"]["model"] = model
    if base_url:
        config["llm"]["base_url"] = base_url

    _write_config(brain_path, config)

    # Write API key to .env (not brain.json — .env is gitignored)
    if api_key and env_var:
        _write_env_key(brain_path, env_var, api_key)

    # Test connection
    test_result = _test_provider(provider, brain_dir)

    emit(envelope(True, "setup", {
        "provider": resolved_provider,
        "model": model,
        "base_url": base_url,
        "config_path": str(brain_path / "brain.json"),
        "test": test_result,
    }))


# ── Interactive mode (for humans) ──────────────────────────────

def run_setup_interactive(brain_dir: str) -> None:
    """Walk the user through LLM setup with prompts."""
    brain_path = Path(brain_dir)

    print("\n=== Eureka LLM Setup ===\n", file=sys.stderr)
    print("How do you want Eureka to call an LLM?\n", file=sys.stderr)

    menu = [
        ("claude-cli", "Claude Code CLI    — uses your Claude Max/Pro subscription (no API key)"),
        ("claude",     "Claude API         — direct Anthropic API (pay-per-token)"),
        ("openai",     "OpenAI API         — GPT-4o, GPT-4.1, etc."),
        ("gemini",     "Gemini CLI         — uses `gemini` CLI on PATH (free tier)"),
        ("ollama",     "Ollama             — local models, no API key"),
        ("openrouter", "OpenRouter         — 200+ models via openrouter.ai"),
        ("together",   "Together AI        — fast open-source models"),
        ("groq",       "Groq               — ultra-fast inference"),
        ("deepseek",   "DeepSeek           — DeepSeek Chat/Coder"),
        ("openai-compatible", "Other        — any OpenAI-compatible endpoint"),
    ]

    for i, (_, label) in enumerate(menu, 1):
        print(f"  {i:2d}. {label}", file=sys.stderr)
    print(file=sys.stderr)

    choice = input(f"Choose [1-{len(menu)}]: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(menu)):
        print(f"Invalid choice: {choice}", file=sys.stderr)
        sys.exit(1)

    provider = menu[int(choice) - 1][0]

    # Resolve spec
    shortcut = SHORTCUTS.get(provider)
    spec = PROVIDERS.get(provider)

    model = None
    api_key = None
    base_url = None

    # Model selection
    if spec and spec["models"]:
        default_model = spec["default_model"]
        print(f"\nAvailable models for {spec['name']}:", file=sys.stderr)
        for i, m in enumerate(spec["models"], 1):
            default_tag = " (default)" if m == default_model else ""
            print(f"  {i}. {m}{default_tag}", file=sys.stderr)
        model_choice = input(f"Choose model [default: {default_model}]: ").strip()
        if model_choice.isdigit() and 1 <= int(model_choice) <= len(spec["models"]):
            model = spec["models"][int(model_choice) - 1]
        else:
            model = default_model
    elif shortcut:
        model = input(f"Model name [default: {shortcut['default_model']}]: ").strip() or shortcut["default_model"]
    elif provider == "openai-compatible":
        model = input("Model name (required): ").strip()
        if not model:
            print("Model name is required.", file=sys.stderr)
            sys.exit(1)
    elif spec:
        model = spec["default_model"]

    # Base URL for openai-compatible or shortcut override
    if provider == "openai-compatible":
        base_url = input("Base URL (e.g. https://api.example.com/v1): ").strip()
        if not base_url:
            print("Base URL is required.", file=sys.stderr)
            sys.exit(1)
    elif shortcut:
        base_url = shortcut["base_url"]

    # API key
    needs_key = (spec and spec["requires_key"]) or (shortcut and shortcut.get("env_var"))
    env_var = (shortcut["env_var"] if shortcut else spec["env_var"]) if needs_key else None

    if needs_key and env_var:
        import os
        existing = os.environ.get(env_var, "")
        if existing:
            print(f"\n{env_var} found in environment.", file=sys.stderr)
        else:
            api_key = input(f"\nEnter {env_var}: ").strip()
            if not api_key:
                print("No key provided. You can set it later in your environment.", file=sys.stderr)
    elif provider == "openai-compatible":
        api_key = input("API key (leave empty if none needed): ").strip() or None

    # Write config (never store API keys in brain.json — they go in .env only)
    config = _load_or_create_config(brain_path)
    config["llm"] = {"provider": provider}
    if model:
        config["llm"]["model"] = model
    if base_url:
        config["llm"]["base_url"] = base_url
    _write_config(brain_path, config)

    if api_key and env_var:
        _write_env_key(brain_path, env_var, api_key)

    # Test
    print("\nTesting connection...", file=sys.stderr)
    test_result = _test_provider(provider, brain_dir)
    if test_result["ok"]:
        resp_preview = test_result.get("response", "")[:80]
        print(f"Connected. Response: {resp_preview}...", file=sys.stderr)
    else:
        print(f"Test failed: {test_result['error']}", file=sys.stderr)

    print(f"\nConfig written to {brain_path / 'brain.json'}", file=sys.stderr)

    emit(envelope(True, "setup", {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "config_path": str(brain_path / "brain.json"),
        "test": test_result,
    }))


# ── Get setup instructions for an agent ────────────────────────

def get_setup_instructions() -> dict:
    """Return structured instructions an agent can follow to configure Eureka.

    The agent should:
    1. Call this to get the provider options
    2. Ask the user which provider they want
    3. Call `eureka setup` with the answer
    """
    return {
        "instructions": (
            "Eureka needs an LLM backend for atom extraction and molecule generation. "
            "Ask the user: do they want to use their Claude/agent subscription, or API tokens? "
            "Then run the matching setup command."
        ),
        "question_to_ask": "Do you want Eureka to use your Claude Code subscription (no extra cost), or API tokens from a provider like OpenAI, Anthropic, Groq, etc.?",
        "options": [
            {
                "id": "claude-cli",
                "name": "Claude Code subscription (Claude Max / Pro)",
                "how": "Uses `claude -p` subprocess. No API key needed. Requires Claude Code CLI installed and authenticated.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider claude-cli --model sonnet",
                "cost": "Included in subscription",
                "best_for": "Users already paying for Claude Max/Pro who want zero additional cost",
            },
            {
                "id": "claude",
                "name": "Claude API (Anthropic)",
                "how": "Direct HTTP calls to api.anthropic.com. Needs ANTHROPIC_API_KEY.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider claude --api-key <KEY>",
                "cost": "Pay-per-token (~$0.25/1M input for Haiku, ~$3/1M for Sonnet)",
                "best_for": "Developers with Anthropic API access",
            },
            {
                "id": "openai",
                "name": "OpenAI API",
                "how": "Direct calls to api.openai.com. Needs OPENAI_API_KEY.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider openai --model gpt-4o-mini --api-key <KEY>",
                "cost": "Pay-per-token",
                "best_for": "Developers with OpenAI API access",
            },
            {
                "id": "gemini",
                "name": "Gemini CLI",
                "how": "Calls `gemini` CLI subprocess. Free tier available.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider gemini",
                "cost": "Free tier available",
                "best_for": "Free LLM calls with decent quality",
            },
            {
                "id": "ollama",
                "name": "Ollama (local)",
                "how": "Local models. No API key, no cost. Requires Ollama running locally.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider ollama --model llama3.1",
                "cost": "Free (runs on your hardware)",
                "best_for": "Privacy-conscious users or offline use",
            },
            {
                "id": "openrouter",
                "name": "OpenRouter (200+ models)",
                "how": "Access any model via openrouter.ai. Needs OPENROUTER_API_KEY.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider openrouter --model anthropic/claude-haiku --api-key <KEY>",
                "cost": "Pay-per-token (varies by model)",
                "best_for": "Users who want model flexibility",
            },
            {
                "id": "together",
                "name": "Together AI",
                "how": "Fast open-source model inference. Needs TOGETHER_API_KEY.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider together --api-key <KEY>",
                "cost": "Pay-per-token",
                "best_for": "Fast, cheap open-source models",
            },
            {
                "id": "groq",
                "name": "Groq",
                "how": "Ultra-fast inference. Needs GROQ_API_KEY.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider groq --api-key <KEY>",
                "cost": "Free tier + pay-per-token",
                "best_for": "Speed-sensitive workflows",
            },
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "how": "DeepSeek API. Needs DEEPSEEK_API_KEY.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider deepseek --api-key <KEY>",
                "cost": "Pay-per-token (very cheap)",
                "best_for": "Budget-conscious users",
            },
            {
                "id": "openai-compatible",
                "name": "Any OpenAI-compatible endpoint",
                "how": "Works with any service that speaks the OpenAI chat completions API. Needs base URL + optional key.",
                "setup_command": "eureka setup --brain-dir <DIR> --provider openai-compatible --base-url https://api.example.com/v1 --model model-name --api-key <KEY>",
                "cost": "Varies",
                "best_for": "Custom or self-hosted endpoints (LM Studio, vLLM, etc.)",
            },
        ],
        "embedding_note": (
            "Separately from LLM, Eureka uses Gemini Embedding 001 for vectors (3072-dim). "
            "Set GEMINI_API_KEY in your brain directory's .env file."
        ),
    }


# ── Helpers ─────────────────────────────────────────────────────

def _load_or_create_config(brain_path: Path) -> dict:
    config_path = brain_path / "brain.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _write_config(brain_path: Path, config: dict) -> None:
    brain_path.mkdir(parents=True, exist_ok=True)
    config_path = brain_path / "brain.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def _write_env_key(brain_path: Path, key_name: str, key_value: str) -> None:
    """Append or update a key in brain_dir/.env."""
    env_path = brain_path / ".env"
    lines = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key_name}="):
                lines.append(f"{key_name}={key_value}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"{key_name}={key_value}")
    env_path.write_text("\n".join(lines) + "\n")


def _test_provider(provider: str, brain_dir: str) -> dict:
    """Send a trivial prompt to verify the provider works."""
    try:
        from eureka.core.llm import get_llm, load_llm_config
        llm = get_llm(config=load_llm_config(brain_dir))
        if llm is None:
            return {"ok": False, "error": "get_llm() returned None — check API keys"}
        response = llm.generate("Reply with exactly: EUREKA_OK")
        return {"ok": "EUREKA_OK" in response.upper() or len(response) > 0, "response": response}
    except Exception as e:
        return {"ok": False, "error": str(e)}
