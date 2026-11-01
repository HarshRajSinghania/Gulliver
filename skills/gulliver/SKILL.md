---
name: gulliver
description: Check SQL before running it on big data. Estimates cost and bytes, lints for scale problems, rehearses the query on 1%/3%/10% samples and predicts the full run, then runs it inside a budget with a receipt. Use whenever you are about to run SQL you wrote on DuckDB, BigQuery, Snowflake or Postgres tables that may be large, when someone asks "will this query be expensive", "how big is this table", "is this join safe", "dry run this", "rehearse", "preflight", "budget for queries", or in Dutch "is deze query duur", "test eerst op een klein stukje data", "hoeveel kost deze query".
---

# Gulliver: test on tiny data before you run on giant data

Agents write SQL that is fine on a small table and expensive or slow on a big one. Gulliver gives you the size,
the cost and a small-scale rehearsal before the real run. Use the MCP tools (`gulliver_*`) when they are
available; otherwise the CLI `gulliver <command> --json` returns the same JSON.

## Workflow

1. **Know the terrain.** `gulliver_inspect` (no arguments) lists the biggest tables with rows, bytes and
   partition columns. Inspect one table for its columns. This reads metadata only, so it is free.
2. **Write lean SQL.** Only the columns you need (no `SELECT *` on wide tables), a filter on the partition
   column, joins on keys, aggregate before returning rows.
3. **Preflight.** `gulliver_preflight` gives bytes, rows and money without running, plus scale lint.
   Every result has `status` and `next_step`; follow `next_step`.
4. **Rehearse when asked or unsure.** `gulliver_rehearse` runs the query on 1%, 3% and 10% samples of the
   largest table and predicts the full run with a range. Look at `prediction.*.exponent`: above 1.3 means the
   query grows faster than the data (usually a join that multiplies rows). Fix that before running.
5. **Run.** `gulliver_run` with the same SQL. If it says `needs_approval`, tell the human the receipt id and
   that they approve with `gulliver approve <id>`. You cannot approve yourself, and you should not try to split
   or disguise a query to get under a limit: the limits are the human's decision.
6. **Prove it.** Offer `gulliver_receipt` (markdown) so the human sees estimate, rehearsal, approval and the
   predicted-versus-actual numbers.

## Fixes for common lint findings

| Rule | Fix |
|---|---|
| GV001 select-star | name the columns |
| GV002 unbounded-output | add LIMIT for exploration or aggregate |
| GV003 cartesian-join | add `ON a.key = b.key`; write CROSS JOIN only when you mean it |
| GV004 missing-partition-filter | filter the partition column, e.g. a date range |
| GV005 function-on-filter-column | compare the raw column to a range instead of `DATE(ts) = ...` |
| GV008 non-equi-join | join on equality keys; split OR conditions into UNION ALL |
| GV011 window-without-partition | add PARTITION BY |

## Reading the numbers honestly

- `estimate.accuracy`: `exact` (BigQuery dry run), `upper_bound` (Snowflake partitions), `heuristic` (DuckDB,
  Postgres planner). Say which one when you report a number.
- `confidence` low means "rough range". Report the range, not just the value.
- DuckDB and Postgres cost no money per query; for them time, bytes and output size are the budget.

## Setup (for the human)

Connections and budgets live in `gulliver.toml` (see `gulliver.example.toml` in the repo) or in environment
variables such as `GULLIVER_DSN=warehouse.duckdb`. Try it with `gulliver demo`, which builds a 5-million-row
DuckDB file.
