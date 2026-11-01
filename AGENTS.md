# Gulliver for agents

Gulliver checks SQL before it touches big data. Use it whenever you are about to run SQL you wrote against a
real table (DuckDB, BigQuery, Snowflake or Postgres), especially when you do not know how big the tables are.

## Tools (MCP) and the matching CLI commands

| MCP tool | CLI | Use it to |
|---|---|---|
| `gulliver_status` | `gulliver status --json` | see connections, budget limits and money spent today |
| `gulliver_inspect` | `gulliver inspect [table] --json` | find the big tables, partitions and columns (free) |
| `gulliver_lint` | `gulliver lint "SQL" --json` | check SQL for scale problems without a database |
| `gulliver_preflight` | `gulliver preflight "SQL" --json` | estimate bytes, rows and money without running |
| `gulliver_rehearse` | `gulliver rehearse "SQL" --json` | run on 1%, 3%, 10% samples and predict the full run |
| `gulliver_run` | `gulliver run "SQL" --json` | run the full query inside the budget |
| `gulliver_receipt` | `gulliver receipt latest` | give the human proof of what happened |

## The loop

1. `gulliver_inspect` once per task, so you know which tables are big and how they are partitioned.
2. Write the SQL. Select only the columns you need. Filter on the partition column. Aggregate before returning rows.
3. `gulliver_preflight`. Read `status` and `next_step`.
4. If `next_step` asks for it (or the estimate is large or only `heuristic`), `gulliver_rehearse`.
5. `gulliver_run` with the exact same SQL. The preview has at most `max_output_rows` rows; `actual.rows` is the total.
6. Offer `gulliver_receipt` to the human.

## Status values

| status | meaning | what to do |
|---|---|---|
| `ok` | within budget | continue |
| `warn` | allowed, with risks listed in `lint` / `warnings` | fix them if cheap, else continue |
| `block` | over a limit, a lint error, or a refused statement | change the SQL; do not work around the gate |
| `needs_rehearsal` | big enough that a rehearsal is required | call `gulliver_rehearse` with the same SQL |
| `needs_approval` | costs more than the auto-approve limit | tell the human the `receipt_id`; they run `gulliver approve <id>` |
| `skipped` | rehearsal not useful (tiny data) | call `gulliver_run` |
| `error` | engine or config problem | read `error`, fix, retry once |

## Reading a rehearsal

`prediction.<metric>.value` is the expected full-run value; `low` and `high` give the range.
`exponent` near 1 means it grows with the data; above 1.3 means it grows faster (a join that multiplies rows).
`confidence` is `high`, `medium` or `low`. Treat `low` as a rough range, not a number.

## Rules you cannot change

- Only one statement per call. Only SELECT, or CREATE/INSERT ... SELECT when a human enabled writes.
- You cannot approve your own runs. Approval is a human CLI command.
- Credentials and budgets are set by the human in `gulliver.toml` or environment variables.
