"""Eureka CLI entrypoint."""

import sys

from eureka.commands.init import run_init
from eureka.commands.ingest import run_ingest
from eureka.commands.status import run_status
from eureka.commands.discover import run_discover
from eureka.commands.review import run_review
from eureka.core.output import emit, envelope


def main():
    args = sys.argv[1:]
    if not args:
        emit(envelope(False, "error", {"message": "No command provided"}))
        sys.exit(1)

    command = args[0]

    if command == "init":
        if len(args) < 2:
            emit(envelope(False, "init", {"message": "Usage: eureka init <brain_dir>"}))
            sys.exit(1)
        run_init(args[1])
    elif command == "ingest":
        if len(args) < 2:
            emit(envelope(False, "ingest", {"message": "Usage: eureka ingest <source> [--brain-dir <dir>]"}))
            sys.exit(1)
        source = args[1]
        brain_dir = None
        if "--brain-dir" in args:
            idx = args.index("--brain-dir")
            if idx + 1 < len(args):
                brain_dir = args[idx + 1]
        if brain_dir is None:
            emit(envelope(False, "ingest", {"message": "--brain-dir is required"}))
            sys.exit(1)
        run_ingest(source, brain_dir)
    elif command == "discover":
        if len(args) < 2:
            emit(envelope(False, "discover", {"message": "Usage: eureka discover <brain_dir>"}))
            sys.exit(1)
        run_discover(args[1])
    elif command == "review":
        if len(args) < 3:
            emit(envelope(False, "review", {"message": "Usage: eureka review <slug> <yes|no> [--brain-dir <dir>]"}))
            sys.exit(1)
        slug = args[1]
        decision = args[2]
        brain_dir = None
        if "--brain-dir" in args:
            idx = args.index("--brain-dir")
            if idx + 1 < len(args):
                brain_dir = args[idx + 1]
        if brain_dir is None:
            emit(envelope(False, "review", {"message": "--brain-dir is required"}))
            sys.exit(1)
        run_review(slug, decision, brain_dir)
    elif command == "serve":
        brain_dir = args[1] if len(args) > 1 else None
        port = 8765
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                port = int(args[idx + 1])
        if brain_dir is None:
            emit(envelope(False, "serve", {"message": "--brain-dir or positional arg required"}))
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
        if len(args) < 3:
            emit(envelope(False, "ask", {"message": "Usage: eureka ask <question> --brain-dir <dir>"}))
            sys.exit(1)
        question = args[1]
        brain_dir = None
        if "--brain-dir" in args:
            idx = args.index("--brain-dir")
            if idx + 1 < len(args):
                brain_dir = args[idx + 1]
        if brain_dir is None:
            emit(envelope(False, "ask", {"message": "--brain-dir is required"}))
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
        emit(envelope("ask", result))
        conn.close()
    elif command == "dump":
        if len(args) < 2:
            emit(envelope(False, "dump", {"message": "Usage: eureka dump <text> --brain-dir <dir>"}))
            sys.exit(1)
        raw_text = args[1]
        brain_dir = None
        if "--brain-dir" in args:
            idx = args.index("--brain-dir")
            if idx + 1 < len(args):
                brain_dir = args[idx + 1]
        if brain_dir is None:
            emit(envelope(False, "dump", {"message": "--brain-dir is required"}))
            sys.exit(1)
        from eureka.core.db import open_db
        from eureka.core.dump import process_dump
        conn = open_db(brain_dir)
        # LLM is required — use Gemini or pass via env
        try:
            from eureka.core.llm import get_llm
            llm = get_llm()
        except Exception:
            emit(envelope(False, "dump", {"message": "No LLM configured. Set EUREKA_LLM or provide llm."}))
            sys.exit(1)
        result = process_dump(raw_text, conn, brain_dir, llm)
        emit(envelope(True, "dump", result))
        conn.close()
    elif command == "profile":
        brain_dir = None
        if "--brain-dir" in args:
            idx = args.index("--brain-dir")
            if idx + 1 < len(args):
                brain_dir = args[idx + 1]
        if brain_dir is None:
            emit(envelope(False, "profile", {"message": "--brain-dir is required"}))
            sys.exit(1)
        from eureka.core.profile import get_questions, process_answers, get_profile
        from eureka.core.db import open_db
        if "--answers" in args:
            idx = args.index("--answers")
            answers_text = args[idx + 1] if idx + 1 < len(args) else ""
            conn = open_db(brain_dir)
            try:
                from eureka.core.llm import get_llm
                llm = get_llm()
            except Exception:
                emit(envelope(False, "profile", {"message": "No LLM configured."}))
                sys.exit(1)
            result = process_answers(conn, brain_dir, answers_text, llm)
            emit(envelope(True, "profile", result))
            conn.close()
        else:
            questions = get_questions()
            emit(envelope(True, "profile", {"questions": questions}))
    elif command == "reflect":
        brain_dir = None
        if "--brain-dir" in args:
            idx = args.index("--brain-dir")
            if idx + 1 < len(args):
                brain_dir = args[idx + 1]
        if brain_dir is None:
            emit(envelope(False, "reflect", {"message": "--brain-dir is required"}))
            sys.exit(1)
        from eureka.core.db import open_db
        from eureka.core.reflect import reflect
        from pathlib import Path
        conn = open_db(brain_dir)
        result = reflect(conn, Path(brain_dir))
        emit(envelope(True, "reflect", result))
        conn.close()
    elif command == "status":
        if len(args) < 2:
            emit(envelope(False, "status", {"message": "Usage: eureka status <brain_dir>"}))
            sys.exit(1)
        run_status(args[1])
    else:
        emit(envelope(False, "error", {"message": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
