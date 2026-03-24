"""Eureka CLI entrypoint."""

import os
import sys

from eureka.commands.init import run_init
from eureka.commands.ingest import run_ingest
from eureka.commands.status import run_status
from eureka.commands.discover import run_discover
from eureka.commands.review import run_review
from eureka.core.output import emit, envelope


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
    flags_with_values = {"--count", "--port", "--brain-dir", "--provider", "--model", "--api-key", "--base-url", "--method"}
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


def main():
    args = sys.argv[1:]
    if not args:
        emit(envelope(False, "error", {"message": "No command provided"}))
        sys.exit(1)

    command = args[0]

    if command in ("--version", "-V"):
        print("eureka 0.3.0")
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

    if command == "init":
        if len(args) < 2:
            emit(envelope(False, "init", {"message": "Usage: eureka init <brain_dir>"}))
            sys.exit(1)
        run_init(args[1])
    elif command == "setup":
        from eureka.commands.setup import run_setup_interactive, run_setup_noninteractive
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "setup", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
        if len(args) < 2:
            emit(envelope(False, "ingest", {"message": "Usage: eureka ingest <source> [--brain-dir <dir>] [--paper]"}))
            sys.exit(1)
        source = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "ingest", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
        # --paper flag forces PaperReader for PDFs
        if "--paper" in args:
            from eureka.readers.paper import PaperReader
            import eureka.commands.ingest as _ingest_mod
            _orig_detect = _ingest_mod.detect_reader
            _ingest_mod.detect_reader = lambda _src: PaperReader()
            run_ingest(source, brain_dir, deep="--deep" in args)
            _ingest_mod.detect_reader = _orig_detect
        else:
            run_ingest(source, brain_dir, deep="--deep" in args)
    elif command == "enrich":
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "enrich", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "discover", {"message": "Brain dir required. Pass as arg or set EUREKA_BRAIN."}))
            sys.exit(1)
        count = 10
        if "--count" in args:
            idx = args.index("--count")
            if idx + 1 < len(args):
                count = int(args[idx + 1])
        method = "all"
        if "--method" in args:
            idx = args.index("--method")
            if idx + 1 < len(args):
                method = args[idx + 1]
        run_discover(brain_dir, method=method, count=count)
    elif command == "review":
        if len(args) < 3:
            emit(envelope(False, "review", {"message": "Usage: eureka review <slug> <yes|no> [--brain-dir <dir>]"}))
            sys.exit(1)
        slug = args[1]
        decision = args[2]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "review", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
        run_review(slug, decision, brain_dir)
    elif command == "serve":
        brain_dir = _get_brain_dir(args) or _get_positional_brain_dir(args)
        port = 8765
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                port = int(args[idx + 1])
        if brain_dir is None:
            emit(envelope(False, "serve", {"message": "Brain dir required. Pass as arg or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "ask", {"message": "Usage: eureka ask <question> [--brain-dir <dir>]"}))
            sys.exit(1)
        question = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "ask", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
        if len(args) < 2:
            emit(envelope(False, "dump", {"message": "Usage: eureka dump <text> [--brain-dir <dir>]"}))
            sys.exit(1)
        raw_text = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "dump", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "profile", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "reflect", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "sync", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "lineage", {"message": "Usage: eureka lineage <slug> [--brain-dir <dir>]"}))
            sys.exit(1)
        slug = args[1]
        brain_dir = _get_brain_dir(args)
        if brain_dir is None:
            emit(envelope(False, "lineage", {"message": "Brain dir required. Pass --brain-dir or set EUREKA_BRAIN."}))
            sys.exit(1)
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
            emit(envelope(False, "status", {"message": "Brain dir required. Pass as arg or set EUREKA_BRAIN."}))
            sys.exit(1)
        run_status(brain_dir)
    else:
        emit(envelope(False, "error", {"message": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
