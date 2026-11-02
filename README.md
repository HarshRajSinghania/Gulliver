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
| 2 | `gulliver_preflight` | Bytes, rows and money **before** running, plus **scale lint** (12 rules) and the budget gate. When a safe rewrite exists, the answer already contains the fixed SQL (`autofix`). |
| 3 | `gulliver_rehearse` | Runs the query on 1%, 3% and 10% samples, fits a growth curve and **predicts the full run** with a confidence range. Catches joins that multiply rows. |
| 4 | `gulliver_run` | Runs the full query only inside the budget. Otherwise answers `needs_rehearsal` or `needs_approval`. |
| 5 | `gulliver_receipt` | Markdown proof for the human: what was estimated, rehearsed, approved and run, and predicted vs actual. |

Every answer has a `status` and a `next_step`, so even small models know what to do next.

Gulliver does not only say no. `gulliver_fix` **rewrites the SQL for the agent** and labels every change.
`same` (exactly the same rows) is only claimed when Gulliver has checked the column types on the connection;
everything else (`assumes`, `nulls`, `changes`) needs `mode=all` and says what may differ. With a connection it
estimates the old and the new query side by side, so nobody has to trust the saving blindly.

And for the pipeline around the query (details in [Pipeline tools](#pipeline-tools)):

| Tool | Problem it solves |
|---|---|
| `gulliver_impact` | "If I change or drop this column, what breaks?" Column-level lineage over SQL models or a dbt manifest. |
| `gulliver_drift` | Schema changed under you: columns removed, retyped or added since the last snapshot, plus the models they break. |
| `gulliver_diff` | "Does my refactored / migrated / incremental model return the same rows?" Key-based data diff inside the engine, also across engines. |
| `gulliver_translate` | SQL between DuckDB, Postgres, BigQuery and Snowflake, with warnings and an optional preflight on the target. |
| `gulliver_incremental` | A model rebuilds everything every run. Is incremental safe, what is the SQL / dbt config, and how many rows does it skip? |
| `gulliver_check` | Data quality in one cheap scan: unique keys, not null, accepted values, ranges, freshness, row-count jumps. |

## Quick start (2 minutes, no warehouse needed)

```bash
pip install gulliver-mcp
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
`3` needs rehearsal or approval, `4` a data check failed, so it also works as a CI check.

## Use it from your agent (MCP)

Gulliver is an MCP server (stdio or Streamable HTTP). Until it is on PyPI, run it straight from GitHub with
[uv](https://docs.astral.sh/uv/):

```bash
uvx gulliver-mcp --dsn path/to/warehouse.duckdb
```

**Claude Code**

```bash
claude mcp add gulliver -- uvx gulliver-mcp --dsn /abs/path/data.duckdb
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
      "args": ["gulliver-mcp", "--config", "/abs/path/gulliver.toml"]
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`):

```toml
[mcp_servers.gulliver]
command = "uvx"
args = ["gulliver-mcp", "--config", "/abs/path/gulliver.toml"]
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
| PostgreSQL | `EXPLAIN (FORMAT JSON)` (heuristic), partition-aware sizes | `TABLESAMPLE ... REPEATABLE` | self-hosted (time and bytes are the budget) | tested in CI against a live Postgres 16 |

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

## Postgres read-only role

Gulliver is read-only by default, but a database role that can only read is a good second layer.
For Postgres, create a dedicated read-only role:

```sql
CREATE ROLE gulliver_ro LOGIN PASSWORD 'your-secure-password';
GRANT USAGE ON SCHEMA public TO gulliver_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO gulliver_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO gulliver_ro;
```

Then connect with that role in `gulliver.toml`:

```toml
[connections.pg]
engine = "postgres"
dsn = "postgresql://gulliver_ro:your-secure-password@localhost:5432/mydb"
```

Also consider setting `statement_timeout` as an extra guard (e.g. via connection options or server-side).

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
`--sample all` samples every table. For BigQuery the sampling is done with `TABLESAMPLE SYSTEM`, which is
block-level and can be less precise on small tables; for the others it is row-level.

## Pipeline tools

These sit next to the query tools. They do not run your query; they look at the SQL and the schema around it.

- `gulliver_impact`: column-level lineage. Point it at a column or a model and see every model that reads it.
- `gulliver_drift`: snapshot the schema, then later compare. Columns that vanished or changed type are flagged,
  plus the models that would break.
- `gulliver_diff`: key-based data diff. Give it two queries (or a query and a table) and it tells you the rows
  that are only on one side, or that differ on the key.
- `gulliver_translate`: SQL dialect translation with a warning list. Optional preflight on the target engine.
- `gulliver_incremental`: for dbt models that rebuild everything. Checks if an incremental strategy is safe,
  suggests the config, and estimates how many rows would be skipped.
- `gulliver_check`: one-pass data quality. Unique, not-null, accepted values, ranges, freshness, row-count jumps.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check
ruff format --check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## License

MIT
