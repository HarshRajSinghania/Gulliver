# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub:
**Security tab → Report a vulnerability** on https://github.com/laaielichter/gulliver.
Do not open a public issue for a vulnerability.

You can expect a first answer within 7 days. Fixed issues are published as a GitHub security advisory.

## Supported versions

Only the latest release gets security fixes.

## What Gulliver is designed to prevent

Gulliver stands between an AI agent and a data warehouse. Its security model:

- Only read statements run by default. Destructive statements (DELETE, UPDATE, DROP, TRUNCATE, ALTER, MERGE)
  and multi-statement input are refused by an SQL parser.
- Writes (CREATE/INSERT ... SELECT) need both the call flag and `allow_write = true` on the connection.
- Budgets fail closed. Approvals are a human-only CLI command, not an MCP tool.
- Credentials are never stored by Gulliver and never shown to the agent (DSN passwords are redacted).
- Local state (`.gulliver/`) holds SQL and result previews; it ships with its own `.gitignore`.

Bypasses of any of these (for example SQL that writes data while classified as a read, or a way for the agent to
approve its own run) are in scope and very welcome reports.
