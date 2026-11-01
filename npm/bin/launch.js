"use strict";

// Thin launcher: runs the Python package gulliver-mcp (same version as this npm package)
// through uv, with pipx as a fallback. stdio is passed straight through, so MCP over stdio works.

const { spawnSync, spawn } = require("node:child_process");
const { version } = require("../package.json");

function pythonSpec() {
  if (process.env.GULLIVER_PY_SPEC) return process.env.GULLIVER_PY_SPEC;
  const extras = (process.env.GULLIVER_EXTRAS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const name = extras.length ? `gulliver-mcp[${extras.join(",")}]` : "gulliver-mcp";
  return `${name}==${version}`;
}

function available(cmd) {
  const r = spawnSync(cmd, ["--version"], { stdio: "ignore" });
  return !r.error && r.status === 0;
}

function runners(command, spec, args) {
  return [
    ["uvx", ["--from", spec, command, ...args]],
    ["uv", ["tool", "run", "--from", spec, command, ...args]],
    ["pipx", ["run", "--spec", spec, command, ...args]],
  ];
}

module.exports = function launch(command) {
  const args = process.argv.slice(2);
  const spec = pythonSpec();
  const found = runners(command, spec, args).find(([bin]) => available(bin));

  if (!found) {
    process.stderr.write(
      [
        "gulliver: this npm package starts the Python package " + spec + ",",
        "but it needs uv (recommended) or pipx, and neither was found.",
        "",
        "Install uv:  https://docs.astral.sh/uv/getting-started/installation/",
        "  macOS/Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh",
        "  Windows:      powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"",
        "",
        "Or skip npm and install directly:  pip install gulliver-mcp",
        "",
      ].join("\n")
    );
    process.exit(1);
  }

  const [bin, binArgs] = found;
  const child = spawn(bin, binArgs, { stdio: "inherit" });

  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => {
      if (!child.killed) child.kill(sig);
    });
  }

  child.on("error", (err) => {
    process.stderr.write(`gulliver: could not start ${bin}: ${err.message}\n`);
    process.exit(1);
  });

  child.on("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code === null ? 1 : code);
  });
};
