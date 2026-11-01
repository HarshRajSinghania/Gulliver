# Gulliver

<!-- mcp-name: io.github.laaielichter/gulliver -->

**Test on tiny data before you run on giant data.**

Gulliver gives AI agents a dress rehearsal for SQL: estimate the cost, rehearse on 1% → 3% → 10% of the data, predict what 100% will do, and only run the full query inside a budget. Local-first, open source, MCP + CLI for any agent and any LLM.

[![ci](https://github.com/laaielichter/gulliver/actions/workflows/ci.yml/badge.svg)](https://github.com/laaielichter/gulliver/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

> In *Gulliver's Travels*, Gulliver visits Lilliput, a land of tiny people, and Brobdingnag, a land of giants.
> Gulliver does the same with your data: it tries your query in Lilliput first, and only walks into Brobdingnag
> when it knows what will happen there.

## Why

Agents write SQL that works on a small table and breaks on a big one. They do not know that `events` has
5 billion rows, that a join multiplies rows, or that a forgotten partition filter scans every day since 2019.
Benchmarks score agents on *is the answer right*, never on *what did it cost* or *does it still work at 100x*.
One unlucky query can burn a monthly budget.

Gulliver sits between the agent and the warehouse:

| Step | Tool | What happens |
|---|---|---|
| 1 | `gulliver_inspect` | Which tables are big? Rows, bytes, partitions, columns. Metadata only, free. |
| 2 | `gulliver_preflight` | Bytes, rows and money **before** running, plus **scale lint** (12 rules) and the budget gate. |
| 3 | `gulliver_rehearse` | Runs the query on 1%, 3% and 10% samples, fits a growth curve and **predicts the full run** with a confidence range. Catches joins that multiply rows. |
| 4 | `gulliver_run` | Runs the full query only inside the budget. Otherwise answers `needs_rehearsal` or `needs_approval`. |
| 5 | `gulliver_receipt` | Markdown proof for the human: what was estimated, rehearsed, approved and run, and predicted vs actual. |

Every answer has a `status` and a `next_step`, so even small models know what to do next.

## Quick start (2 minutes, no warehouse needed)

```bash
pip install git+https://github.com/laaielichter/gulliver
gulliver demo                       # creates gulliver_demo.duckdb with 5M events
export GULLIVER_DSN=gulliver_demo.duckdb

gulliver inspect
gulliver preflight "select country, count(*) from events e join users u on e.user_id = u.user_id group by 1"
gulliver lint "select * from events e, users u"           # GV003: join without a condition -> blocked
gulliver rehearse "select a.event_id, b.event_id from events a join events b on a.user_id = b.user_id"
```

The last one is the classic agent mistake: a self-join on a non-unique key. The rehearsal sees the output grow
with exponent ~1.8 instead of ~1 and warns that the full result has more than 100 million rows, before you run it.

```
| Sample | Runtime  | Output rows |
|--------|----------|-------------|
| 1%     | 0.0202s  | 41,706      |
| 3%     | 0.0484s  | 237,422     |
| 10%    | 0.3909s  | 2,438,395   |

Prediction for 100%: output rows 134,525,654 (range 67,262,827 - 269,051,308)
Growth exponent output_rows: 1.77 -> grows faster than the data
```

Add `--json` to any command for machine-readable output. Exit codes: `0` ok, `1` error, `2` blocked,
`3` needs rehearsal or approval, so it also works as a CI check.

## Use it from your agent (MCP)

Gulliver is an MCP server (stdio or Streamable HTTP). Until it is on PyPI, run it straight from GitHub with
[uv](https://docs.astral.sh/uv/):

```bash
uvx --from git+https://github.com/laaielichter/gulliver gulliver-mcp --dsn path/to/warehouse.duckdb
```

**Claude Code**

```bash
claude mcp add gulliver -- uvx --from git+https://github.com/laaielichter/gulliver gulliver-mcp --dsn /abs/path/data.duckdb
```

Or install it as a plugin (MCP server + skill):

```
/plugin marketplace add laaielichter/gulliver
/plugin install gulliver@gulliver
```

**Claude Desktop, Cursor, Windsurf, VS Code and other MCP clients** (JSON config):

```json
{
  "mcpServers": {
    "gulliver": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/laaielichter/gulliver", "gulliver-mcp", "--config", "/abs/path/gulliver.toml"]
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`):

```toml
[mcp_servers.gulliver]
command = "uvx"
args = ["--from", "git+https://github.com/laaielichter/gulliver", "gulliver-mcp", "--config", "/abs/path/gulliver.toml"]
```

**Gemini CLI** (`~/.gemini/settings.json`): same `mcpServers` block as above.

**Any HTTP client or remote agent:** `gulliver-mcp --http --port 8765` serves `http://127.0.0.1:8765/mcp`.

**No MCP?** Every tool is also a CLI command with `--json`, and `gulliver tools --format openai` or
`--format gemini` prints ready-made function-calling definitions for the OpenAI or Gemini APIs.

## Engines

| Engine | Estimate before running | Sampling | Money model | Status |
|---|---|---|---|---|
| DuckDB (files, Parquet, CSV, in-memory) | EXPLAIN + metadata (heuristic) | `TABLESAMPLE` system/bernoulli, seeded | free (time is the budget) | tested in CI |
| BigQuery | dry run: **exact** bytes | `TABLESAMPLE SYSTEM` | on-demand $/TiB, plus a hard `maximum_bytes_billed` cap | beta, tested with fakes |
| Snowflake | `EXPLAIN USING JSON`: bytes and partitions (upper bound) | `SAMPLE SYSTEM ... SEED` | warehouse credits x runtime | beta, tested with fakes |
| PostgreSQL | `EXPLAIN (FORMAT JSON)` (heuristic) | `TABLESAMPLE ... REPEATABLE` | self-hosted (time and bytes are the budget) | beta, tested with fakes |

Install the drivers you need: `pip install "gulliver-mcp[bigquery]"`, `[snowflake]`, `[postgres]` or `[all]`.
Every estimate says how much to trust it: `exact`, `upper_bound` or `heuristic`. A heuristic is never called exact.

## Configuration

Copy [`gulliver.example.toml`](gulliver.example.toml) to `gulliver.toml`:

```toml
default_connection = "local"

[connections.local]
engine = "duckdb"
path = "warehouse.duckdb"

[connections.bq]
dsn = "bigquery://my-project?location=EU"
dataset = "analytics"
price_per_tib_usd = 6.25

[budget]
max_query_usd = 1.00        # hard stop for one query
approval_over_usd = 0.25    # above this a human runs `gulliver approve <receipt_id>`
rehearse_over_usd = 0.10    # above this a rehearsal is required first
day_usd = 10.00             # total per day (local ledger)
max_runtime_s = 900
max_output_rows = 200       # rows handed back to the agent
```

Or skip the file: `GULLIVER_DSN`, `GULLIVER_MAX_QUERY_USD`, `GULLIVER_DAY_USD` and friends.
Credentials never go in the config: Gulliver uses each engine's own environment variables and credential chains
(Google ADC, `SNOWFLAKE_PASSWORD`, `PGPASSWORD`, ...). The agent only ever sees connection *names*.

## Safety model

- **Read-first.** Only `SELECT` (and `WITH ... SELECT`) runs by default. `DELETE`, `UPDATE`, `DROP`, `TRUNCATE`,
  `ALTER`, `MERGE`, several statements at once and unparsable SQL are refused by a parser, not a regex.
- **Writes need two keys.** `CREATE TABLE ... AS SELECT` and `INSERT ... SELECT` run only when the call says
  `allow_write` **and** a human set `allow_write = true` on that connection. Rehearsals never write.
- **Budgets fail closed.** Over the per-query, per-day, bytes or runtime limit means `block`. Money above the
  approval limit needs `gulliver approve <receipt_id>`, a CLI command for humans that is not exposed as an MCP tool.
- **Engine-side caps** where they exist: BigQuery `maximum_bytes_billed`, Snowflake and Postgres statement timeouts,
  a DuckDB interrupt timer.
- **Local state only.** Receipts, the spend ledger and approvals live in `./.gulliver/` as JSON. No telemetry.

## How the prediction works

Each rung measures runtime, output rows and (where the engine reports it) bytes. Gulliver fits
`metric = a * fraction^k` in log-log space and reads off the value at 100%.

- `k ≈ 1`: grows with the data (scans, filters, key joins against a full table).
- `k ≈ 0`: flat (aggregations). Group counts saturate, so grouped results are capped by what was observed and the planner estimate.
- `k > 1.3`: grows faster than the data: a join that multiplies rows, a big sort, or both join sides sampled. Flagged.

Runtime first subtracts the fixed per-query overhead (measured with `SELECT 1`). Confidence is `high`, `medium`
or `low`, with a range of x0.7-1.5, x0.5-2 or x0.25-4. After a real run, the receipt shows predicted vs actual.

By default only the **largest** table is sampled and the others stay complete, which keeps key joins honest.
`--sample all` samples every table. For BigQuery the money prediction uses the exact dry-run bytes of the full query.

**Limits, honestly:** block (system) sampling is cheap but can be skewed on clustered data; use `--method bernoulli`
when that matters. Extrapolating 10x always has uncertainty; Gulliver shows it instead of hiding it. Databricks,
ClickHouse and Spark are not supported yet.

## Scale lint rules

| Rule | Name | Severity |
|---|---|---|
| GV001 | select-star | warn |
| GV002 | unbounded-output | warn |
| GV003 | cartesian-join | error (no condition) / warn (CROSS JOIN) |
| GV004 | missing-partition-filter | error |
| GV005 | function-on-filter-column | warn |
| GV006 | order-without-limit | warn |
| GV007 | exact-count-distinct | info |
| GV008 | non-equi-join | warn |
| GV009 | union-distinct | info |
| GV010 | scalar-subquery-in-select | info |
| GV011 | window-without-partition | warn |
| GV012 | not-in-subquery | info |

`gulliver lint` works without any database.

## CLI reference

```
gulliver status                       connections, budget, spend today
gulliver inspect [TABLE]              biggest tables, or one table's columns
gulliver lint SQL [--dialect D]       scale lint only
gulliver preflight SQL                estimate + lint + gate, no execution
gulliver rehearse SQL [--fractions 0.01,0.03,0.1] [--sample largest|all] [--method auto|system|bernoulli]
gulliver run SQL [--max-rows N] [--allow-write]
gulliver receipt [ID|latest] [--format markdown|json]
gulliver approve ID [--note TEXT]     (human only)
gulliver demo [PATH]                  create a demo DuckDB database
gulliver tools --format mcp|openai|gemini
gulliver mcp [--http]                 start the MCP server
```

SQL can be an argument, `-f file.sql`, or `-` for stdin. Global flags: `--dsn`, `--config`, `-c NAME`, `--json`.

## Development

```bash
git clone https://github.com/laaielichter/gulliver && cd gulliver
pip install -e ".[dev]"
pytest
```

See [AGENTS.md](AGENTS.md) for the agent-facing guide and [SECURITY.md](SECURITY.md) to report a vulnerability.

## License

MIT, see [LICENSE](LICENSE).
