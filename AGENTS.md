# Gulliver for agents

Gulliver checks SQL before it touches big data. Use it whenever you are about to run SQL you wrote against a
real table (DuckDB, BigQuery, Snowflake or Postgres), especially when you do not know how big the tables are.

## Tools (MCP) and the matching CLI commands

| MCP tool | CLI | Use it to |
|---|---|---|
| `gulliver_status` | `gulliver status --json` | see connections, budget limits and money spent today |
| `gulliver_inspect` | `gulliver inspect [table] --json` | find the big tables, partitions and columns (free) |
| `gulliver_lint` | `gulliver lint "SQL" --json` | check SQL for scale problems without a database |
| `gulliver_fix` | `gulliver fix "SQL" --json` | rewrite SQL to be cheaper; each change says if the rows stay the same |
| `gulliver_preflight` | `gulliver preflight "SQL" --json` | estimate bytes, rows and money without running |
| `gulliver_rehearse` | `gulliver rehearse "SQL" --json` | run on 1%, 3%, 10% samples and predict the full run |
| `gulliver_run` | `gulliver run "SQL" --json` | run the full query inside the budget |
| `gulliver_receipt` | `gulliver receipt latest` | give the human proof of what happened |
| `gulliver_impact` | `gulliver impact table.column --models DIR` | see which models and columns a change breaks |
| `gulliver_drift` | `gulliver drift --models DIR` | see schema changes since the last snapshot and what they break |
| `gulliver_diff` | `gulliver diff --left Q --right Q --key id` | prove two queries/tables return the same rows |
| `gulliver_translate` | `gulliver translate SQL --to bigquery` | move SQL between DuckDB, Postgres, BigQuery, Snowflake |
| `gulliver_incremental` | `gulliver incremental SQL --time-column ts` | make a full-rebuild model incremental, with the saving |
| `gulliver_check` | `gulliver check table --unique id ...` | data quality in one scan (status `fail` if a check fails) |

## The loop

1. `gulliver_inspect` once per task, so you know which tables are big and how they are partitioned.
2. Write the SQL. Select only the columns you need. Filter on the partition column. Aggregate before returning rows.
3. `gulliver_preflight`. Read `status` and `next_step`. If the result has `autofix`, use `autofix.fixed_sql`
   (exactly the same rows, cheaper) and preflight that instead.
4. If `next_step` asks for it (or the estimate is large or only `heuristic`), `gulliver_rehearse`.
5. `gulliver_run` with the exact same SQL. The preview has at most `max_output_rows` rows; `actual.rows` is the total.
6. Offer `gulliver_receipt` to the human.

## Pipeline work

- Before changing or dropping a column in a model or source: `gulliver_impact` with the models folder.
- After refactoring a model, migrating it to another engine or making it incremental: `gulliver_diff` between the
  old and the new query with the key. Say "identical" only when `identical` is true.
- When a model rebuilds everything each run: `gulliver_incremental`; present the strategy, the SQL and the saving,
  and verify with `gulliver_diff`.
- Before trusting a table or after a load: `gulliver_check` (unique keys, not null, freshness). On partitioned
  tables pass `where` with a partition filter.
- Periodically, or when a pipeline breaks: `gulliver_drift` with the models folder.

## Status values

| status | meaning | what to do |
|---|---|---|
| `ok` | within budget | continue |
| `warn` | allowed, with risks listed in `lint` / `warnings` | fix them if cheap, else continue |
| `block` | over a limit, a lint error, or a refused statement | change the SQL; do not work around the gate |
| `needs_rehearsal` | big enough that a rehearsal is required | call `gulliver_rehearse` with the same SQL |
| `needs_approval` | costs more than the auto-approve limit | tell the human the `receipt_id`; they run `gulliver approve <id>` |
| `skipped` | rehearsal not useful (tiny data) | call `gulliver_run` |
| `fail` | a data quality check failed | report which checks failed; do not use the data as if it were fine |
| `error` | engine or config problem | read `error`, fix, retry once |

## Reading a rehearsal

`prediction.<metric>.value` is the expected full-run value; `low` and `high` give the range.
`exponent` near 1 means it grows with the data; above 1.3 means it grows faster (a join that multiplies rows).
`confidence` is `high`, `medium` or `low`. Treat `low` as a rough range, not a number.

## Rules you cannot change

- Only one statement per call. Only SELECT, or CREATE/INSERT ... SELECT when a human enabled writes.
- You cannot approve your own runs. Approval is a human CLI command.
- Credentials and budgets are set by the human in `gulliver.toml` or environment variables.
