"""Eureka CLI entrypoint."""

import os
import sys

from eureka.commands.init import run_init
from eureka.commands.ingest import run_ingest
from eureka.commands.status import run_status
from eureka.commands.discover import run_discover
from eureka.commands.review import run_review
from eureka.core.output import emit, envelope

# Per-command help text: options + examples, printed to stderr so JSON isn't broken.
COMMAND_HELP = {
    "init": (
        "Usage: eureka init <dir>\n\n"
        "Create a new brain directory with an empty database.\n\n"
        "Examples:\n"
        "  eureka init ~/mybrain\n"
        "  eureka init /tmp/testbrain\n"
    ),
    "setup": (
        "Usage: eureka setup [options]\n\n"
        "Configure LLM provider. Interactive by default; pass flags for non-interactive.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --provider <name>   LLM provider (gemini, openai, ollama, claude-code)\n"
        "  --model <name>      Model name\n"
        "  --api-key <key>     API key\n"
        "  --base-url <url>    Custom base URL (for ollama etc.)\n\n"
        "Examples:\n"
        "  eureka setup --brain-dir ~/mybrain\n"
        "  eureka setup --brain-dir ~/mybrain --provider gemini --api-key AIza...\n"
        "  eureka setup --brain-dir ~/mybrain --provider ollama --base-url http://localhost:11434\n"
    ),
    "ingest": (
        "Usage: eureka ingest <source> [options]\n\n"
        "Add a source (file, URL, arxiv ID) to the brain.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --paper             Force paper reader for PDFs\n"
        "  --deep              Recursively fetch referenced papers (1 level)\n"
        "  --title <name>      Override source title\n"
        "  --stdin             Read raw text from stdin instead of <source>\n\n"
        "Examples:\n"
        "  eureka ingest ~/books/thinking-fast.pdf --brain-dir ~/mybrain\n"
        "  eureka ingest https://arxiv.org/abs/2301.00001 --paper --deep --brain-dir ~/mybrain\n"
        "  eureka ingest notes.txt --title \"Field Notes\" --brain-dir ~/mybrain\n"
        "  cat transcript.txt | eureka ingest --stdin --brain-dir ~/mybrain\n"
    ),
    "discover": (
        "Usage: eureka discover [options]\n\n"
        "Find molecule candidates and write the top ones.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --count <N>         Number of candidates (default: 10)\n"
        "  --method <name>     Discovery method (triangle, void, walk, bridge, all)\n"
        "  --dry-run           Preview candidates without writing molecules\n\n"
        "Examples:\n"
        "  eureka discover --brain-dir ~/mybrain\n"
        "  eureka discover --brain-dir ~/mybrain --count 5 --method triangle\n"
        "  eureka discover --brain-dir ~/mybrain --dry-run\n"
    ),
    "ask": (
        "Usage: eureka ask <question> [options]\n\n"
        "Query the brain using graph-aware retrieval.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n\n"
        "Examples:\n"
        "  eureka ask \"What do I know about mimetic desire?\" --brain-dir ~/mybrain\n"
        "  eureka ask \"How does antifragility relate to habits?\" --brain-dir ~/mybrain\n"
    ),
    "dump": (
        "Usage: eureka dump <text> [options]\n\n"
        "Extract atoms from raw text and connect to existing brain.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --stdin             Read text from stdin instead of positional arg\n\n"
        "Examples:\n"
        "  eureka dump \"I think staying broad is underrated\" --brain-dir ~/mybrain\n"
        "  pbpaste | eureka dump --stdin --brain-dir ~/mybrain\n"
    ),
    "review": (
        "Usage: eureka review <slug> <yes|no> [options]\n\n"
        "Accept or reject a molecule candidate.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n\n"
        "Examples:\n"
        "  eureka review stress-and-subtraction yes --brain-dir ~/mybrain\n"
        "  eureka review weak-molecule no --brain-dir ~/mybrain\n"
    ),
    "status": (
        "Usage: eureka status [options]\n\n"
        "Show brain health and stats.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n\n"
        "Examples:\n"
        "  eureka status --brain-dir ~/mybrain\n"
        "  EUREKA_BRAIN=~/mybrain eureka status\n"
    ),
    "serve": (
        "Usage: eureka serve [options]\n\n"
        "Start the visual dashboard.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --port <N>          Port number (default: 8765)\n\n"
        "Examples:\n"
        "  eureka serve --brain-dir ~/mybrain\n"
        "  eureka serve --brain-dir ~/mybrain --port 9000\n"
    ),
    "sync": (
        "Usage: eureka sync [options]\n\n"
        "Sync .md files with brain.db.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --dry-run           Preview changes without applying\n\n"
        "Examples:\n"
        "  eureka sync --brain-dir ~/mybrain\n"
        "  eureka sync --brain-dir ~/mybrain --dry-run\n"
    ),
    "lineage": (
        "Usage: eureka lineage <slug> [options]\n\n"
        "Trace source → atom → molecule chain for a slug.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n\n"
        "Examples:\n"
        "  eureka lineage barbell-strategy --brain-dir ~/mybrain\n"
    ),
    "profile": (
        "Usage: eureka profile [options]\n\n"
        "Onboarding questions & profile. Without --answers, returns questions.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n"
        "  --answers <text>    Submit answers (JSON or freeform)\n\n"
        "Examples:\n"
        "  eureka profile --brain-dir ~/mybrain\n"
        "  eureka profile --brain-dir ~/mybrain --answers '{\"q1\": \"data science\"}'\n"
    ),
    "reflect": (
        "Usage: eureka reflect [options]\n\n"
        "Generate a reflection based on brain state.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n\n"
        "Examples:\n"
        "  eureka reflect --brain-dir ~/mybrain\n"
    ),
    "enrich": (
        "Usage: eureka enrich [options]\n\n"
        "Enrich reference stubs via Semantic Scholar.\n\n"
        "Options:\n"
        "  --brain-dir <dir>   Brain directory (or set EUREKA_BRAIN)\n\n"
        "Examples:\n"
        "  eureka enrich --brain-dir ~/mybrain\n"
    ),
}


def _show_command_help(command, sub_args):
    """If --help or -h is in sub_args, print command help to stderr and exit 0. Returns True if handled."""
    if "--help" in sub_args or "-h" in sub_args:
        help_text = COMMAND_HELP.get(command, f"No help available for '{command}'.\n")
        print(help_text, file=sys.stderr, end="")
        sys.exit(0)
    return False


def _get_brain_dir(args):
    """Resolve brain directory from --brain-dir flag, positional arg, or EUREKA_BRAIN env var."""
    # Explicit --brain-dir flag
    if "--brain-dir" in args:
        idx = args.index("--brain-dir")
        if idx + 1 < len(args):
            return args[idx + 1]
    # Env var
    env_dir = os.environ.get("EUREKA_BRAIN")
    if env_dir:
        return env_dir
    return None


def _get_positional_brain_dir(args):
    """Find positional brain_dir arg, skipping flags and their values."""
    skip_next = False
    flags_with_values = {"--count", "--port", "--brain-dir", "--provider", "--model", "--api-key", "--base-url", "--method", "--title"}
    for i, arg in enumerate(args[1:], 1):  # skip command name
        if skip_next:
            skip_next = False
            continue
        if arg in flags_with_values:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        return arg
    return None


def _brain_dir_error(command, usage):
    """Emit actionable error for missing brain dir."""
    emit(envelope(False, command, {
        "message": "Brain dir required.",
        "usage": usage,
        "hint": "Or set EUREKA_BRAIN environment variable.",
    }))
    sys.exit(1)


def main():
    args = sys.argv[1:]
    if not args:
        emit(envelope(False, "error", {"message": "No command provided"}))
        sys.exit(1)

    command = args[0]
    sub_args = args[1:]  # everything after the command name

    if command in ("--version", "-V"):
        print("eureka 0.3.2")
        sys.exit(0)

    if command in ("--help", "-h", "help"):
        print(
            "Usage: eureka <command> [options]\n\n"
            "Commands:\n"
            "  init <dir>              Create a new brain (auto-detects LLM)\n"
            "  setup                   Configure LLM provider (interactive)\n"
            "  setup-instructions      Get setup options as JSON (for agents)\n"
            "  ingest <source>         Add a source (file, URL, arxiv:ID)\n"
            "  discover [--count N]    Find & write molecule candidates\n"
            "  ask <question>          Query the brain (graph-aware retrieval)\n"
            "  dump <text>             Extract atoms from raw text\n"
            "  review <slug> yes|no    Accept or reject a molecule\n"
            "  status                  Brain health & stats\n"
            "  profile [--answers ..]  Onboarding questions & profile\n"
            "  reflect                 Generate a reflection\n"
            "  enrich                  Enrich reference stubs via Semantic Scholar\n"
            "  sync [--dry-run]        Sync .md files with brain.db\n"
            "  lineage <slug>          Trace source→atom→molecule chain\n"
            "  serve [--port N]        Start visual dashboard\n\n"
            "Options:\n"
            "  --brain-dir <dir>       Brain directory (or set EUREKA_BRAIN)\n"
            "  --method <name>         Discovery method (triangle,void,walk,bridge,...)\n"
            "  --paper                 Force paper reader for PDFs\n"
            "  --deep                  Recursively fetch referenced papers (1 level)\n"
            "  --version               Show version\n"
            "  --help                  Show this help\n",
            file=sys.stderr,
        )
        sys.exit(0)

    # Per-command --help (task 1)
    if command in COMMAND_HELP:
        _show_command_help(command, sub_args)

    if command == "init":
        if len(args) < 2:
            emit(envelope(False, "init", {
                "message": "Missing argument.",
                "usage": "eureka init <brain_dir>",
            }))
            sys.exit(1)
        run_init(args[1])
    elif command == "setup":
        from eureka.commands.setup import run_setup_interactive, run_setup_noninteractive
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("setup", "eureka setup --brain-dir <dir>")
        # Non-interactive mode: --provider flag present
        if "--provider" in args:
            idx = args.index("--provider")
            provider = args[idx + 1] if idx + 1 < len(args) else None
            model = None
            if "--model" in args:
                midx = args.index("--model")
                model = args[midx + 1] if midx + 1 < len(args) else None
            api_key = None
            if "--api-key" in args:
                kidx = args.index("--api-key")
                api_key = args[kidx + 1] if kidx + 1 < len(args) else None
            base_url = None
            if "--base-url" in args:
                bidx = args.index("--base-url")
                base_url = args[bidx + 1] if bidx + 1 < len(args) else None
            run_setup_noninteractive(brain_dir, provider, model=model, api_key=api_key, base_url=base_url)
        else:
            run_setup_interactive(brain_dir)
    elif command == "setup-instructions":
        from eureka.commands.setup import get_setup_instructions
        emit(envelope(True, "setup-instructions", get_setup_instructions()))
    elif command == "ingest":
        # --stdin support (task 3)
        use_stdin = "--stdin" in args
        if not use_stdin and len(args) < 2:
            emit(envelope(False, "ingest", {
                "message": "Missing source argument.",
                "usage": "eureka ingest <source> [--brain-dir <dir>]",
                "hint": "Or pipe text via: cat file.txt | eureka ingest --stdin --brain-dir <dir>",
            }))
            sys.exit(1)
        if use_stdin:
            source = None  # will be read from stdin inside run_ingest
        else:
            source = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("ingest", "eureka ingest <source> --brain-dir <dir>")
        # --title flag for custom source name
        title_override = None
        if "--title" in args:
            tidx = args.index("--title")
            title_override = args[tidx + 1] if tidx + 1 < len(args) else None
        # When --stdin, read text and write to a temp file for the reader
        if use_stdin:
            import tempfile
            stdin_text = sys.stdin.read()
            if not stdin_text.strip():
                emit(envelope(False, "ingest", {"message": "No input received on stdin."}))
                sys.exit(1)
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            tmp.write(stdin_text)
            tmp.close()
            source = tmp.name
            if title_override is None:
                title_override = "stdin input"
        # --paper flag forces PaperReader for PDFs
        if "--paper" in args:
            from eureka.readers.paper import PaperReader
            import eureka.commands.ingest as _ingest_mod
            _orig_detect = _ingest_mod.detect_reader
            _ingest_mod.detect_reader = lambda _src: PaperReader()
            run_ingest(source, brain_dir, deep="--deep" in args, title_override=title_override)
            _ingest_mod.detect_reader = _orig_detect
        else:
            run_ingest(source, brain_dir, deep="--deep" in args, title_override=title_override)
    elif command == "enrich":
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("enrich", "eureka enrich --brain-dir <dir>")
        from eureka.core.db import open_db
        from eureka.core.citation_graph import enrich_stubs
        conn = open_db(brain_dir)
        try:
            result = enrich_stubs(
                conn, [],  # references not needed — reads stubs from DB
                progress_callback=lambda i, n, t: print(f"  [{i}/{n}] {t}", file=sys.stderr, flush=True),
            )
            # Re-embed if any stubs were enriched
            if result.get("enriched", 0) > 0:
                from eureka.core.embeddings import ensure_embeddings
                from eureka.core.linker import link_all
                from pathlib import Path
                print("Re-embedding enriched stubs...", file=sys.stderr, flush=True)
                ensure_embeddings(conn, Path(brain_dir))
                link_all(conn)
            emit(envelope(True, "enrich", result))
        finally:
            conn.close()
    elif command == "discover":
        brain_dir = _get_brain_dir(args) or _get_positional_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("discover", "eureka discover --brain-dir <dir>")
        count = 10
        if "--count" in args:
            idx = args.index("--count")
            if idx + 1 < len(args):
                try:
                    count = int(args[idx + 1])
                except ValueError:
                    emit(envelope(False, "discover", {"message": f"--count requires an integer, got '{args[idx + 1]}'"}))
                    sys.exit(1)
        method = "all"
        if "--method" in args:
            idx = args.index("--method")
            if idx + 1 < len(args):
                method = args[idx + 1]
        # --dry-run support (task 2)
        dry_run = "--dry-run" in args
        run_discover(brain_dir, method=method, count=count, dry_run=dry_run)
    elif command == "review":
        if len(args) < 3:
            emit(envelope(False, "review", {
                "message": "Missing arguments.",
                "usage": "eureka review <slug> <yes|no> --brain-dir <dir>",
            }))
            sys.exit(1)
        slug = args[1]
        decision = args[2]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("review", "eureka review <slug> <yes|no> --brain-dir <dir>")
        run_review(slug, decision, brain_dir)
    elif command == "serve":
        brain_dir = _get_brain_dir(args) or _get_positional_brain_dir(args)
        port = 8765
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                try:
                    port = int(args[idx + 1])
                except ValueError:
                    emit(envelope(False, "serve", {"message": f"--port requires an integer, got '{args[idx + 1]}'"}))
                    sys.exit(1)
        if brain_dir is None:
            _brain_dir_error("serve", "eureka serve --brain-dir <dir>")
        from eureka.core.server import create_app
        import sys as _sys
        app = create_app(brain_dir)
        server = app["server_factory"](port)
        print(f"Eureka dashboard: http://localhost:{port}", file=_sys.stderr, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
    elif command == "ask":
        if len(args) < 2:
            emit(envelope(False, "ask", {
                "message": "Missing question argument.",
                "usage": "eureka ask <question> --brain-dir <dir>",
            }))
            sys.exit(1)
        question = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("ask", "eureka ask <question> --brain-dir <dir>")
        import struct
        from eureka.core.db import open_db
        from eureka.core.ask import ask
        conn = open_db(brain_dir)
        rows = conn.execute("SELECT slug, vector FROM embeddings").fetchall()
        embeddings = {}
        for r in rows:
            dim = len(r["vector"]) // 4
            embeddings[r["slug"]] = list(struct.unpack(f"{dim}f", r["vector"]))
        result = ask(question, conn, embeddings)
        emit(envelope(True, "ask", result))
        conn.close()
    elif command == "dump":
        # --stdin support (task 3)
        use_stdin = "--stdin" in args
        if not use_stdin and len(args) < 2:
            emit(envelope(False, "dump", {
                "message": "Missing text argument.",
                "usage": "eureka dump <text> --brain-dir <dir>",
                "hint": "Or pipe text via: echo 'thoughts' | eureka dump --stdin --brain-dir <dir>",
            }))
            sys.exit(1)
        if use_stdin:
            raw_text = sys.stdin.read()
            if not raw_text.strip():
                emit(envelope(False, "dump", {"message": "No input received on stdin."}))
                sys.exit(1)
        else:
            raw_text = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("dump", "eureka dump <text> --brain-dir <dir>")
        from eureka.core.db import open_db
        from eureka.core.dump import process_dump
        conn = open_db(brain_dir)
        from eureka.core.llm import get_llm, load_llm_config
        try:
            llm = get_llm(config=load_llm_config(brain_dir))
        except RuntimeError as e:
            emit(envelope(False, "dump", {"message": str(e)}))
            sys.exit(1)
        if llm is None:
            emit(envelope(False, "dump", {"message": "No LLM found. Install Claude Code or run `eureka setup`."}))
            sys.exit(1)
        result = process_dump(raw_text, conn, brain_dir, llm)
        emit(envelope(True, "dump", result))
        conn.close()
    elif command == "profile":
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("profile", "eureka profile --brain-dir <dir>")
        from eureka.core.profile import get_questions, process_answers, get_profile
        from eureka.core.db import open_db
        if "--answers" in args:
            idx = args.index("--answers")
            answers_text = args[idx + 1] if idx + 1 < len(args) else ""
            conn = open_db(brain_dir)
            from eureka.core.llm import get_llm as _get_llm_profile, load_llm_config as _load_profile
            try:
                llm = _get_llm_profile(config=_load_profile(brain_dir))
            except RuntimeError as e:
                emit(envelope(False, "profile", {"message": str(e)}))
                sys.exit(1)
            if llm is None:
                emit(envelope(False, "profile", {"message": "No LLM found. Install Claude Code or run `eureka setup`."}))
                sys.exit(1)
            result = process_answers(conn, brain_dir, answers_text, llm)
            emit(envelope(True, "profile", result))
            conn.close()
        else:
            questions = get_questions()
            emit(envelope(True, "profile", {"questions": questions}))
    elif command == "reflect":
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("reflect", "eureka reflect --brain-dir <dir>")
        from eureka.core.db import open_db
        from eureka.core.reflect import reflect
        from pathlib import Path
        conn = open_db(brain_dir)
        result = reflect(conn, Path(brain_dir))
        emit(envelope(True, "reflect", result))
        conn.close()
    elif command == "sync":
        brain_dir = _get_brain_dir(args) or _get_positional_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("sync", "eureka sync --brain-dir <dir>")
        from eureka.core.db import open_db
        from eureka.core.sync import run_sync
        from pathlib import Path
        conn = open_db(brain_dir)
        try:
            result = run_sync(conn, Path(brain_dir), dry_run="--dry-run" in args)
            emit(envelope(True, "sync", result))
        finally:
            conn.close()
    elif command == "lineage":
        if len(args) < 2:
            emit(envelope(False, "lineage", {
                "message": "Missing slug argument.",
                "usage": "eureka lineage <slug> --brain-dir <dir>",
            }))
            sys.exit(1)
        slug = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("lineage", "eureka lineage <slug> --brain-dir <dir>")
        from eureka.core.db import open_db
        from eureka.core.lineage import trace_lineage
        conn = open_db(brain_dir)
        try:
            result = trace_lineage(conn, slug)
            if result is None:
                emit(envelope(False, "lineage", {"message": f"Slug '{slug}' not found in atoms or molecules."}))
                sys.exit(3)
            else:
                emit(envelope(True, "lineage", result))
        finally:
            conn.close()
    elif command == "status":
        brain_dir = _get_brain_dir(args) or _get_positional_brain_dir(args)
        if brain_dir is None:
            _brain_dir_error("status", "eureka status --brain-dir <dir>")
        run_status(brain_dir)
    else:
        emit(envelope(False, "error", {"message": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
