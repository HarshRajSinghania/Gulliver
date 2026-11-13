# Changelog

## Unreleased

### Changed
- CLI help and README reference now document `demo --events/--overwrite`, `incremental --no-savings` and `mcp --host/--port` (and matching `gulliver-mcp` help). No behavior change. (#124)

## 0.4.0 - 2026-11-11

Data checks you define once in `gulliver.toml` and run in CI, a lint baseline for existing repos, rehearsal
calibration, receipt listing and pruning, three new lint rules, and stricter refusal of bad budgets, config keys
and flags. Thanks to 14 outside contributors.

### Added
- Refuse inspect limits outside 1-200 and sensitive value scans outside 0-1000 instead of silently clamping them (#97). A named table still ignores the listing limit.
- Data quality checks in `gulliver.toml` under `[checks.<name>]`: run them by name with `gulliver check NAME` or run all configured targets in CI with `gulliver check --all` (exits 4 if any check fails) (#80).
- `gulliver rules --format markdown|json` prints a generated rule table (markdown) or the same JSON as `--json`; the README Scale lint rules table is generated from it (#18).
- `gulliver spend -o/--output PATH` and `gulliver top -o/--output PATH` write the report as UTF-8 and print a one-line confirmation (#19).
- Opt-in `check --samples N` / MCP `samples` (0-20) reports guarded offending values and row counts for failed unique, accepted-values and range checks. Each extra query is budget-gated and logged; blocked or failed samples leave the check result intact (#48, #49).
- Lint rule GV016 `order-by-random`: warns on `ORDER BY RANDOM()` / `RAND()`, also with LIMIT, and points to `TABLESAMPLE` / `USING SAMPLE` for random sampling (#23).
- Prompt-injection scan: new `override_i18n` signal for "ignore previous instructions" in Dutch, German, French and Spanish (#22).
- Lint rule GV017 `deep-offset`: warns when an `OFFSET` is an integer literal of 10,000 or more and suggests keyset pagination (#30).
- Lint rule GV018 `count-for-existence`: flags `(SELECT COUNT(*) ...)` compared with zero (`> 0`, `>= 1`, `<> 0`, `= 0`, `< 1` and the mirrored `0 < ...`, also with `COUNT(1)`) and suggests `EXISTS`, or `NOT EXISTS` for `= 0` and `< 1` (#31).
- Result guard: npm (`npm_...`), PyPI (`pypi-...`) and Hugging Face (`hf_...`) tokens are tagged `api_key` and masked inside free text (#38).
- `gulliver calibration [--days N] [-c NAME]` and the `gulliver://calibration` MCP resource show how often rehearsal ranges held up against real runs, per metric and confidence level. New run receipts store `low`, `high` and `confidence` in `predicted_vs_actual` (#47).
- `gulliver receipt --list [--limit N] [--status STATUS] [--json]` lists recent receipts newest first, with summary fields only (no preview rows), so you can find a receipt without knowing its id (#39, #60).
- `gulliver diff` says which columns differ for changed keys ("Rows differ in: country (1 key)"), computed inside the existing keys query, so no extra queries run and no values leave the engine (#46, #69).
- `gulliver prune [--older-than 30d] [--keep-last N] [--dry-run]` cleans up old receipts and expired approvals while `gulliver audit verify` keeps passing (#79).
- `gulliver lint --baseline FILE` / `--write-baseline [FILE]` and `[lint] baseline`: record today's findings and report (and fail on) only new ones on an existing repo. Findings match by path, rule and source line, so moved lines still match and copies or edits are new. The JSON result gets `baselined` and `baseline_fixed` (#45).

### Thanks
- @bfs2021 for refusing NaN, infinite and negative budget limits (#40) and the GV001 fix for EXISTS subqueries (#50).
- @mayankdhingra02 for the guarded samples in `gulliver check` (#49) and the rehearsal calibration report (#61).
- @shaw778 for the derived `gulliver_lint` rule range (#41), the npm, PyPI and Hugging Face token shapes (#58), lint rule GV017 (#59), column-level `gulliver diff` (#69) and its follow-up test and note fix (#72).
- @ariktadas144 for the non-English prompt-injection signal (#62).
- @Doomguy-BFG9000 for escaping `|` and `~` in composite keys and diffs (#53).
- @17302513901yh-lang for refusing unknown lint rule ids (#54), the GV002 fix for aggregates inside subqueries (#64) and lint rule GV018 (#66), and @ariktadas144 for the careful review of it.
- @Muhtasim-Munif-Fahim for `gulliver rules --format markdown|json` and the generated README rule table (#68), and `spend -o` / `top -o` (#67).
- @ariktadas144 for `gulliver lint --baseline`, so existing repos only see new findings (#90).
- @shaw778 for `gulliver prune`, which cleans up receipts without breaking the audit chain (#88), and for checks defined in `gulliver.toml` with `gulliver check NAME` and `check --all` (#105).
- @yinbowen-dc for refusing out-of-range `inspect` limits and sensitive scan sizes (#99).
- @hamid-digitalmarketer for refusing `spend`, `calibration` and `top` windows and limits below one (#95).
- @Abhishekpandey123-git for `gulliver receipt --list` (#60).
