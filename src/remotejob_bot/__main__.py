"""Command line entry point for the small public framework."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "run-once":
        from .run_once import main as run_once_main

        return run_once_main(args[1:])
    if "--demo" in args:
        from .demo import main as demo_main

        return demo_main(args)
    print("Usage: python -m remotejob_bot --demo [options] | run-once [options]")
    return 0 if not args or args == ["--help"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
