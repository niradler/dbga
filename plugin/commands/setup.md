---
description: Install the dbga debugger CLI and report toolchain readiness for Python, Go, and Node
---

Install the `dbga` debugger CLI for the user and confirm it works. This is a
convenience installer — no hooks, no PATH hacking, no background processes.

## Steps

1. **Check if `dbga` is already installed.** Run `dbga --version`. If it prints
   a version, skip installation and report it as already present.

2. **Install `dbga`** using the first available tool, in this order. Each is a
   mutating command — run it directly here since the user invoked this installer
   explicitly:
   - `uv tool install dbga`  (preferred)
   - else `pipx install dbga`
   - else `pip install --user dbga`

   If none of `uv`, `pipx`, or `pip` is available, stop and tell the user to
   install one (recommend `uv`), then re-run `/debug-agent:setup`.

3. **Confirm.** Run `dbga --version` and report the version. If it is not on
   PATH after install, tell the user the install location and how to add it
   (e.g. `uv tool` puts binaries in a dir shown by `uv tool dir`).

4. **Report language toolchain readiness** (do NOT auto-install these — `dbga`
   only needs them for the languages the user actually debugs):
   - **Python** — debugpy is bundled; nothing extra needed.
   - **Go** — check `dlv version`. If missing, note:
     `go install github.com/go-delve/delve/cmd/dlv@latest`
   - **Node** — check `node --version`, and note that vscode-js-debug is
     required (VS Code/Cursor bundle it; otherwise extract a
     `js-debug-dap-*.tar.gz` release or set `$DBGA_JS_DEBUG_SERVER`). See the
     `debug-agent` skill's Languages table for discovery order.

## Output

A short summary: `dbga` version (or install result), then a one-line readiness
status per language (ready / install command). Keep it terse.
