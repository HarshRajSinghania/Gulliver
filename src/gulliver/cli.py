"""Command line: the same workflow as the MCP tools, with --json for agents and scripts.

Exit codes: 0 ok/warn/skipped, 1 error, 2 block, 3 needs_rehearsal / needs_approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, core
from .config import ConfigError, load_settings

EXIT = {"ok": 0, "warn": 0, "skipped": 0, "error": 1, "block": 2, "needs_rehearsal": 3, "needs_approval": 3}


def _read_sql(args: argparse.Namespace) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text()
    if args.sql == "-" or (args.sql is None and not sys.stdin.isatty()):
        return sys.stdin.read()
    if not args.sql:
        raise SystemExit("gulliver: give SQL as an argument, with -f file.sql, or on stdin")
    return args.sql


def _print_human(result: dict[str, Any]) -> None:
    from .receipts import render_markdown

    if "markdown" in result:
        print(result["markdown"])
        return
    if result.get("receipt_id") and result.get("action"):
        print(render_markdown(result))
        preview = result.get("preview")
        if preview:
            print("## Preview\n")
            cols = result.get("columns") or list(preview[0])
            print(" | ".join(cols))
            for row in preview[:20]:
                print(" | ".join(str(row.get(c)) for c in cols))
            if result.get("truncated"):
                print(f"... ({result.get('actual', {}).get('rows', '?')} rows in total)")
        return
    if "tables" in result and isinstance(result["tables"], list):
        print(f"{'table':40} {'rows':>14} {'bytes':>12}  partitioned_by")
        for t in result["tables"]:
            print(f"{t['name'][:40]:40} {t.get('rows', ''):>14} {core._fmt_bytes(t.get('bytes')):>12}  "
                  f"{t.get('partitioned_by', '')}")
        print(f"\nnext: {result.get('next_step', '')}")
        return
    if "table" in result:
        t = result["table"]
        print(f"{t['name']}: {t.get('rows', '?')} rows, {core._fmt_bytes(t.get('bytes'))}")
        if t.get("partitioned_by"):
            print(f"partitioned by: {t['partitioned_by']}")
        if t.get("clustered_by"):
            print(f"clustered by: {t['clustered_by']}")
        for c in t.get("columns") or []:
            print(f"  {c['name']:30} {c['type']}")
        print(f"\nnext: {result.get('next_step', '')}")
        return
    if "lint" in result and "counts" in result:
        if not result["lint"]:
            print("No scale problems found.")
        for item in result["lint"]:
            print(f"{item['severity']:5} {item['rule']} {item['name']}: {item['message']}\n      fix: {item['fix']}")
        print(f"\nnext: {result.get('next_step', '')}")
        return
    print(json.dumps(result, indent=2, default=str))


def _emit(result: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)
    return EXIT.get(str(result.get("status")), 1)


def _add_common(p: argparse.ArgumentParser, defaults: bool) -> None:
    extra: dict[str, Any] = {} if defaults else {"default": argparse.SUPPRESS}
    p.add_argument("--config", help="Path to gulliver.toml (default: ./gulliver.toml or $GULLIVER_CONFIG)", **extra)
    p.add_argument("--dsn", help="Connection string: file.duckdb, postgresql://..., bigquery://project, ...", **extra)
    p.add_argument("-c", "--connection", help="Connection name from gulliver.toml", **extra)
    if defaults:
        p.add_argument("--json", action="store_true", help="Print JSON (for agents and scripts)")
    else:
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print JSON")


def _add_sql_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("sql", nargs="?", help="SQL text, or '-' to read stdin")
    p.add_argument("-f", "--file", help="Read the SQL from a file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gulliver",
        description="Test on tiny data before you run on giant data.",
        epilog="Workflow: inspect -> preflight -> rehearse -> run -> receipt. Docs: "
               "https://github.com/laaielichter/gulliver",
    )
    parser.add_argument("--version", action="version", version=f"gulliver {__version__}")
    _add_common(parser, defaults=True)
    # The same flags also work after the command (gulliver status --json).
    common = argparse.ArgumentParser(add_help=False)
    _add_common(common, defaults=False)
    sub = parser.add_subparsers(dest="command", required=True)
    _orig_add = sub.add_parser

    def add_parser(name: str, **kwargs: Any) -> argparse.ArgumentParser:
        return _orig_add(name, parents=[common], **kwargs)

    sub.add_parser = add_parser  # type: ignore[method-assign]

    sub.add_parser("status", help="Connections, budget and spend today")

    p = sub.add_parser("inspect", help="Biggest tables, or one table's columns")
    p.add_argument("table", nargs="?")
    p.add_argument("--limit", type=int, default=25)

    p = sub.add_parser("lint", help="Scale lint only (no database needed)")
    _add_sql_args(p)
    p.add_argument("--dialect", default=None, help="duckdb, postgres, bigquery or snowflake")

    p = sub.add_parser("preflight", help="Estimate cost and size without running")
    _add_sql_args(p)

    p = sub.add_parser("rehearse", help="Run on 1%%, 3%%, 10%% samples and predict the full run")
    _add_sql_args(p)
    p.add_argument("--fractions", help="Comma-separated, e.g. 0.01,0.03,0.1")
    p.add_argument("--sample", choices=["largest", "all"], default="largest")
    p.add_argument("--method", choices=["auto", "system", "bernoulli"], default="auto")
    p.add_argument("--seed", type=int, default=42)

    p = sub.add_parser("run", help="Run the full query inside the budget")
    _add_sql_args(p)
    p.add_argument("--max-rows", type=int, default=None)
    p.add_argument("--allow-write", action="store_true", help="Allow CREATE/INSERT ... SELECT "
                                                             "(the connection must allow it too)")

    p = sub.add_parser("receipt", help="Show a receipt")
    p.add_argument("receipt_id", nargs="?", default="latest")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")

    p = sub.add_parser("approve", help="(Human) approve a run that is over the auto-approve limit")
    p.add_argument("receipt_id")
    p.add_argument("--note", default="")

    p = sub.add_parser("demo", help="Create a demo DuckDB database (5M events) to try Gulliver")
    p.add_argument("path", nargs="?", default="gulliver_demo.duckdb")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--events", type=int, default=5_000_000)

    p = sub.add_parser("tools", help="Print tool definitions for MCP, OpenAI or Gemini function calling")
    p.add_argument("--format", choices=["mcp", "openai", "gemini"], default="mcp")

    p = sub.add_parser("mcp", help="Start the MCP server (same as gulliver-mcp)")
    p.add_argument("--http", action="store_true")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            from .demo import build_demo

            return _emit(build_demo(args.path, events=args.events, overwrite=args.overwrite), args.json)
        if args.command == "tools":
            from .mcp_server import export_tools

            print(json.dumps(export_tools(args.format), indent=2))
            return 0
        if args.command == "mcp":
            from .mcp_server import main as mcp_main

            forwarded = []
            if args.config:
                forwarded += ["--config", args.config]
            if args.dsn:
                forwarded += ["--dsn", args.dsn]
            if args.http:
                forwarded += ["--http", "--host", args.host, "--port", str(args.port)]
            mcp_main(forwarded)
            return 0
        if args.command == "lint":
            dialect = args.dialect
            if dialect is None:
                try:
                    settings = load_settings(config_path=args.config, dsn=args.dsn)
                    from .engines import dialect_for

                    dialect = dialect_for(settings.connection(args.connection).engine)
                except ConfigError:
                    dialect = "duckdb"
            return _emit(core.lint_sql(_read_sql(args), dialect), args.json)

        settings = load_settings(config_path=args.config, dsn=args.dsn)
        conn = args.connection
        if args.command == "status":
            result = core.status(settings)
        elif args.command == "inspect":
            result = core.inspect(settings, connection=conn, table=args.table, limit=args.limit)
        elif args.command == "preflight":
            result = core.preflight(settings, _read_sql(args), connection=conn)
        elif args.command == "rehearse":
            fractions = [float(x) for x in args.fractions.split(",")] if args.fractions else None
            result = core.rehearse(settings, _read_sql(args), connection=conn, fractions=fractions,
                                   sample=args.sample, method=args.method, seed=args.seed)
        elif args.command == "run":
            result = core.run(settings, _read_sql(args), connection=conn, max_rows=args.max_rows,
                              allow_write=args.allow_write)
        elif args.command == "receipt":
            result = core.get_receipt(settings, args.receipt_id, fmt=args.format)
        elif args.command == "approve":
            result = core.approve(settings, args.receipt_id, note=args.note)
        else:  # pragma: no cover - argparse guards this
            parser.error(f"unknown command {args.command}")
            return 2
        return _emit(result, args.json)
    except ConfigError as exc:
        return _emit({"status": "error", "error": str(exc), "next_step": "Fix gulliver.toml or the flags."}, args.json)
    except ValueError as exc:
        return _emit({"status": "error", "error": str(exc), "next_step": "Check the arguments."}, args.json)
    except KeyboardInterrupt:
        return 130


def entrypoint() -> None:  # pragma: no cover
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
