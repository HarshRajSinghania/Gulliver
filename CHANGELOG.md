# Changelog

## Unreleased

- New `gulliver_fix` (MCP) / `gulliver fix` (CLI): rewrites SQL to be cheaper and labels every change with a
  guarantee (`same`, `nulls`, `changes`). Safe by default: date filters such as `DATE(ts) = '...'`, `ts::date`,
  `DATE_TRUNC`, `YEAR`/`EXTRACT(YEAR ...)` become ranges on the raw column; useless ORDER BY in CTEs and subqueries
  is removed. `mode=all` adds NOT IN → NOT EXISTS, approximate distinct counts, UNION ALL and a LIMIT. With a
  connection it estimates before and after.
- `gulliver_preflight` and `gulliver_lint` include `autofix.fixed_sql` when a same-rows rewrite exists, so the
  agent gets the fix without an extra call.
- Claude Code plugin installs the MCP server from PyPI (`uvx gulliver-mcp`).

## 0.1.0 - 2026-11-01

First release.

Query rehearsal:
- Workflow: `status`, `inspect`, `lint`, `preflight`, `rehearse`, `run`, `receipt`, `approve`.
- Rehearsal ladder (1% → 3% → 10%), power-law extrapolation with confidence ranges, detection of super-linear growth,
  saturation cap for grouped results.
- 12 scale lint rules (GV001-GV012).
- Budget gate: per query, per day, bytes, runtime, rehearsal requirement and human approval.

Pipeline tools:
- `impact` / `lineage`: column-level lineage over SQL model folders (dbt Jinja supported) or a dbt manifest.
- `snapshot` / `drift`: schema drift per connection, mapped to impacted models.
- `diff`: key-based data diff inside the engines with MD5 buckets and a zoom-in pass; works across engines.
- `translate`: SQL between DuckDB, Postgres, BigQuery and Snowflake, with warnings and an optional target preflight.
- `incremental`: append / partition_overwrite / merge_recompute / not_safe advice, generated SQL and dbt config,
  measured savings.
- `check`: unique, not null, accepted values, range, freshness and row-count change in one scan (exit code 4 on fail).

Engines and integration:
- DuckDB and PostgreSQL tested (Postgres live in CI), BigQuery and Snowflake beta (tested with fakes).
- MCP server (stdio and Streamable HTTP), CLI with `--json`, OpenAI and Gemini tool export.
- Claude Code plugin and agent skill.
