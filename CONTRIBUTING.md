# Contributing to Gulliver

Thanks for helping. Small fixes and big ideas are both welcome.

## Ways to help

- Report a bug or ask a question with the issue forms.
- Pick an issue labeled `good first issue`.
- Add a scale lint rule, an auto-fix, or an engine (ClickHouse, Databricks, ...).
- Improve the docs or add an example from a real pipeline.

## Set up

```bash
git clone https://github.com/laaielichter/Gulliver.git
cd Gulliver
pip install -e ".[dev]"
pytest
ruff check .
```

`gulliver demo` builds a local DuckDB file with 5 million rows to try things on. Postgres tests run when
`GULLIVER_TEST_PG_DSN` points at a database; CI runs them against Postgres 16.

## Where things live

| Path | What |
|---|---|
| `src/gulliver/core.py` | the workflow: status, inspect, preflight, rehearse, run, receipts |
| `src/gulliver/lint.py` | scale lint rules (GV001 ...) |
| `src/gulliver/fixer.py` | auto-fix rewrites and their guarantees |
| `src/gulliver/engines/` | one adapter per warehouse |
| `src/gulliver/features.py` | impact, drift, diff, translate, incremental, check |
| `src/gulliver/mcp_server.py`, `cli.py` | thin wrappers: MCP tools and the CLI |

## Rules for changes

- **Read-only by default.** Nothing may write data unless a human enabled it on the connection.
- **Honest numbers.** Every estimate says how accurate it is (`exact`, `upper_bound`, `heuristic`).
- **A "same rows" rewrite must be proven.** Add a test that runs the original and the rewritten SQL on real
  data and compares the rows. If it is not always the same, use another guarantee (`assumes`, `nulls`,
  `changes`) and keep it out of the default mode.
- **Every result has `status` and `next_step`**, so small models know what to do.

## Pull requests

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep each pull request to one change.
3. Add or update tests and docs (README, AGENTS.md, llms.txt, the skill) when behaviour changes.
4. Describe what changed and why. CI must be green on Linux, Windows and macOS.

## Be kind

We follow the [Code of Conduct](CODE_OF_CONDUCT.md). Be patient and specific; we will do the same.

Security problems: please report them privately, see [SECURITY.md](SECURITY.md).
