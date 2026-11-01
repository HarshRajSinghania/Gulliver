# gulliver-mcp (npm launcher)

**Test on tiny data before you run on giant data.**

Gulliver gives AI agents a dress rehearsal for SQL: estimate the cost, rehearse on 1% → 3% → 10% of the data,
predict what 100% will do, and only run the full query inside a budget. Local-first, open source, MCP + CLI.

This npm package is a small launcher. Gulliver itself is written in Python and published on PyPI as
[`gulliver-mcp`](https://pypi.org/project/gulliver-mcp/). The launcher starts the matching Python version for you.

Full documentation: https://github.com/laaielichter/Gulliver

## Requirements

- Node 18 or newer
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pipx

No Python setup needed beyond that: uv downloads what it needs the first time.

## Use it from your agent (MCP)

Claude Code:

```bash
claude mcp add gulliver -- npx -y gulliver-mcp --dsn /abs/path/data.duckdb
```

Any MCP client with a JSON config:

```json
{
  "mcpServers": {
    "gulliver": {
      "command": "npx",
      "args": ["-y", "gulliver-mcp", "--config", "/abs/path/gulliver.toml"]
    }
  }
}
```

## Use the CLI

```bash
npx -p gulliver-mcp gulliver demo
npx -p gulliver-mcp gulliver preflight "select count(*) from events" --dsn gulliver_demo.duckdb
```

## Warehouse drivers

DuckDB works out of the box. For other engines, set `GULLIVER_EXTRAS`:

```bash
GULLIVER_EXTRAS=postgres npx -y gulliver-mcp --dsn postgresql://...
GULLIVER_EXTRAS=bigquery,snowflake npx -y gulliver-mcp --config gulliver.toml
```

Advanced: `GULLIVER_PY_SPEC` overrides the full Python package spec (for example a local path).

## Without npm

```bash
uvx gulliver-mcp --dsn path/to/warehouse.duckdb
# or
pip install gulliver-mcp
```

## License

MIT
