"""MCP server: the Gulliver workflow as tools for any MCP client (Claude, Codex, Gemini CLI, Cursor, ...).

Start it with `gulliver-mcp` (stdio) or `gulliver-mcp --http --port 8765` (Streamable HTTP).
Connections and budgets come from gulliver.toml / environment variables, never from the agent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Annotated, Any, Literal

from pydantic import Field

from . import __version__, core
from .config import ConfigError, load_settings

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover - mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from mcp.types import ToolAnnotations

INSTRUCTIONS = """Gulliver is a dress rehearsal for SQL on big data. Use it before running SQL you wrote on real tables.

Workflow:
1. gulliver_status: connections, budget, money spent today.
2. gulliver_inspect: which tables are big, their columns and partitions.
3. gulliver_preflight: cost/bytes estimate + scale lint for your SQL. Read status and next_step.
4. gulliver_rehearse: when preflight says needs_rehearsal (or you are unsure), runs your SQL on 1%, 3%, 10% samples
   and predicts the full run (runtime, rows, money) with a confidence level.
5. gulliver_run: runs the full query only inside the budget. It may answer needs_rehearsal or needs_approval
   (a human approves with `gulliver approve <receipt_id>`; you cannot approve yourself).
6. gulliver_receipt: markdown proof of what was estimated, rehearsed, approved and run.

Every result has `status` and `next_step`. Follow next_step. Status block means: do not try to work around it,
change the SQL. Only SELECT, and CREATE/INSERT ... SELECT (when a human enabled writes), are accepted."""

_ARGS: dict[str, Any] = {"config": None, "dsn": None}


def _settings():
    return load_settings(config_path=_ARGS["config"], dsn=_ARGS["dsn"])


def _guard(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(_settings(), *args, **kwargs)
    except ConfigError as exc:
        return {"status": "error", "error": str(exc),
                "next_step": "Ask the human to fix gulliver.toml or the GULLIVER_* environment variables."}
    except Exception as exc:  # never crash the server on one bad call
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}",
                "next_step": "Report this error to the human; it is a Gulliver bug or an engine problem."}


SQL = Annotated[str, Field(description="One SQL statement in the connection's dialect.")]
CONNECTION = Annotated[str | None, Field(description="Connection name from gulliver_status. Omit for the default.")]

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RUNS_QUERIES = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=False)
GATED_RUN = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def build_server() -> Any:
    server = _Server(name="gulliver", instructions=INSTRUCTIONS)

    @server.tool(name="gulliver_status", annotations=READ_ONLY,
                 description="Show connections, budget limits and money spent today. Call this first.")
    def gulliver_status() -> dict[str, Any]:
        return _guard(core.status)

    @server.tool(name="gulliver_inspect", annotations=READ_ONLY,
                 description="List the biggest tables (rows, bytes, partitions), or show one table's columns. "
                             "Free: reads metadata only.")
    def gulliver_inspect(
        table: Annotated[str | None, Field(description="Table to describe, e.g. 'events' or 'proj.ds.events'. "
                                                       "Omit to list tables.")] = None,
        connection: CONNECTION = None,
        limit: Annotated[int, Field(description="Max tables to list.", ge=1, le=200)] = 25,
    ) -> dict[str, Any]:
        return _guard(core.inspect, connection=connection, table=table, limit=limit)

    @server.tool(name="gulliver_lint", annotations=READ_ONLY,
                 description="Scale lint only (no database): find SQL patterns that are fine on small data and "
                             "expensive on big data, with fixes.")
    def gulliver_lint(
        sql: SQL,
        dialect: Annotated[Literal["duckdb", "postgres", "bigquery", "snowflake"],
                           Field(description="SQL dialect.")] = "duckdb",
    ) -> dict[str, Any]:
        try:
            return core.lint_sql(sql, dialect)
        except Exception as exc:
            return {"status": "error", "error": str(exc), "next_step": "Check the SQL and dialect."}

    @server.tool(name="gulliver_preflight", annotations=READ_ONLY,
                 description="Estimate bytes, rows and money for a query WITHOUT running it, plus scale lint and the "
                             "budget gate. Always call before gulliver_run.")
    def gulliver_preflight(sql: SQL, connection: CONNECTION = None) -> dict[str, Any]:
        return _guard(core.preflight, sql, connection=connection)

    @server.tool(name="gulliver_rehearse", annotations=RUNS_QUERIES,
                 description="Run the query on small samples (default 1%, 3%, 10% of the largest table), measure "
                             "runtime/rows/bytes and predict the full run with a confidence range. Costs a fraction "
                             "of the full run. Never writes data.")
    def gulliver_rehearse(
        sql: SQL,
        connection: CONNECTION = None,
        fractions: Annotated[list[float] | None, Field(description="Sample sizes between 0 and 1. "
                                                                   "Default [0.01, 0.03, 0.1].")] = None,
        sample: Annotated[Literal["largest", "all"], Field(description="Sample only the largest table (default, "
                                                                       "keeps joins honest) or every table.")] = "largest",
        method: Annotated[Literal["auto", "system", "bernoulli"],
                          Field(description="Sampling method. auto picks block sampling for big tables.")] = "auto",
    ) -> dict[str, Any]:
        return _guard(core.rehearse, sql, connection=connection, fractions=fractions, sample=sample, method=method)

    @server.tool(name="gulliver_run", annotations=GATED_RUN,
                 description="Run the full query inside the budget. Returns a preview of rows plus totals. May "
                             "answer needs_rehearsal or needs_approval instead of running.")
    def gulliver_run(
        sql: SQL,
        connection: CONNECTION = None,
        max_rows: Annotated[int | None, Field(description="Rows to return as preview (capped by the budget).",
                                              ge=0)] = None,
        allow_write: Annotated[bool, Field(description="Needed for CREATE/INSERT ... SELECT; the connection must "
                                                       "also allow writes.")] = False,
    ) -> dict[str, Any]:
        return _guard(core.run, sql, connection=connection, max_rows=max_rows, allow_write=allow_write)

    @server.tool(name="gulliver_receipt", annotations=READ_ONLY,
                 description="Get a receipt (proof) of a preflight, rehearsal or run, as markdown for a human or "
                             "as JSON.")
    def gulliver_receipt(
        receipt_id: Annotated[str, Field(description="receipt_id from an earlier result, or 'latest'.")] = "latest",
        format: Annotated[Literal["markdown", "json"], Field(description="Output format.")] = "markdown",
    ) -> dict[str, Any]:
        return _guard(core.get_receipt, receipt_id, fmt=format)

    return server


def tool_schemas() -> list[dict[str, Any]]:
    """The MCP tool list as plain dicts: name, description, inputSchema."""
    server = build_server()
    tools = asyncio.run(server.list_tools())
    out = []
    for tool in tools:
        data = tool.model_dump(by_alias=True, exclude_none=True) if hasattr(tool, "model_dump") else dict(tool)
        schema = data.get("inputSchema") or data.get("input_schema") or {"type": "object", "properties": {}}
        out.append({"name": data["name"], "description": data.get("description", ""), "inputSchema": schema})
    return out


def _strip_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_strip_titles(v) for v in schema]
    return schema


def _flatten_nullable(schema: Any) -> Any:
    """Gemini's function schema has no anyOf/null: turn `anyOf: [X, null]` into X."""
    if isinstance(schema, dict):
        if "anyOf" in schema:
            options = [o for o in schema["anyOf"] if o.get("type") != "null"]
            if len(options) == 1:
                merged = {k: v for k, v in schema.items() if k != "anyOf"}
                merged.update(options[0])
                return _flatten_nullable(merged)
        return {k: _flatten_nullable(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_flatten_nullable(v) for v in schema]
    return schema


def export_tools(fmt: str = "mcp") -> Any:
    """Tool definitions for other function-calling APIs (same source as the MCP server)."""
    tools = tool_schemas()
    if fmt == "mcp":
        return tools
    if fmt == "openai":
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": _strip_titles(t["inputSchema"])}} for t in tools]
    if fmt == "gemini":
        return {"function_declarations": [
            {"name": t["name"], "description": t["description"],
             "parameters": _flatten_nullable(_strip_titles(t["inputSchema"]))} for t in tools]}
    raise ValueError("format must be mcp, openai or gemini")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gulliver-mcp", description="Gulliver MCP server (stdio by default).")
    parser.add_argument("--config", help="Path to gulliver.toml")
    parser.add_argument("--dsn", help="Connection string, e.g. path/to/file.duckdb or bigquery://project")
    parser.add_argument("--http", action="store_true", help="Serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--version", action="version", version=f"gulliver-mcp {__version__}")
    args = parser.parse_args(argv)
    _ARGS.update(config=args.config, dsn=args.dsn)
    try:
        load_settings(config_path=args.config, dsn=args.dsn)
    except ConfigError as exc:
        print(f"gulliver-mcp: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    server = build_server()
    if not args.http:
        server.run("stdio")
        return
    import inspect

    if "host" in inspect.signature(server.run_streamable_http_async).parameters:  # mcp >= 2
        server.run("streamable-http", host=args.host, port=args.port)
    else:  # pragma: no cover - mcp 1.x keeps host/port in settings
        server.settings.host = args.host
        server.settings.port = args.port
        server.run("streamable-http")


if __name__ == "__main__":  # pragma: no cover
    main()
