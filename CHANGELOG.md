# Changelog

## Unreleased

- Add `docs/tutorial.md`: a step-by-step walkthrough of the inspect → preflight → lint → fix → rehearse → run → receipt loop on the bundled demo database (#134).

### Added
- Refuse inspect limits outside 1-200 and sensitive value scans outside 0-1000 instead of silently clamping them (#97). A named table still ignores the listing limit.
- `gulliver rules --format markdown|json` prints a generated rule table (markdown) or the same JSON as `--json`; the README Scale lint rules table is generated from it (#18).
- `gulliver spend -o/--output PATH` and `gulliver top -o/--output PATH` write the report as UTF-8 and print a one-line confirmation (#19).
