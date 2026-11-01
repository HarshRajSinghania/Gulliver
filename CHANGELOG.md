# Changelog

## 0.1.0 - 2026-11-01

First release.

- Workflow: `status`, `inspect`, `lint`, `preflight`, `rehearse`, `run`, `receipt`, `approve`.
- Rehearsal ladder (1% → 3% → 10%), power-law extrapolation with confidence ranges, detection of super-linear growth.
- 12 scale lint rules (GV001-GV012).
- Engines: DuckDB (tested), BigQuery, Snowflake, PostgreSQL (beta).
- Budget gate: per query, per day, bytes, runtime, rehearsal requirement and human approval.
- MCP server (stdio and Streamable HTTP), CLI with `--json`, OpenAI and Gemini tool export.
- Claude Code plugin and agent skill.
