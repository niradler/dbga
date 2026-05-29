# debug-agent

**Evidence-first multi-language debugger CLI for AI agents.**
Python (via `debugpy`) · Go (via `dlv dap`) · Node.js / TypeScript (via vscode-js-debug).

A stateless command-line interface on top of the Debug Adapter Protocol that
returns machine-readable, auto-contextualized JSON on every stop: location, source
around the stop, locals, full stack, recent output, and warnings — all in a
single response. Designed so an AI coding agent (or a human at a terminal)
can drive a real debugger in the same way it edits files: one command, one
structured result, no hidden state.

```sh
dbga session start --break-at app.py:42 -- script.py
dbga session eval --expr "len(items)"
dbga session continue --break "loader.py:30:not records"
dbga session release
```

## Why

Print-statement debugging gives you one value per round-trip. A debugger
gives you the whole picture — but `pdb` and raw `debugpy` are stateful TUIs
designed for humans, not pipelines. `debug-agent` exposes the same observability
through a flat, scriptable CLI:

- **Auto-context on every stop.** No follow-up `where` / `inspect` / `list`
  calls. The first response tells you where you are, what's around you, what
  the locals look like, and what the stack is.
- **Stateless surface, stateful core.** Each command is independent; a
  background daemon owns the live DAP connection so the session survives
  across calls.
- **Multi-session.** `--session NAME` runs concurrent debuggees side by side.
- **Multi-tool.** `run` for bounded execution, `watch` for log scans, `localize`
  for traceback parsing, `instrument` for reversible source probes, `diagnose`
  for one-call crash-to-paused triage, `--listen` for VS Code attach.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
# Zero-install — run from a one-shot uv environment
uvx dbga --version

# Persistent install into a uv-managed tool environment
uv tool install dbga
dbga --version

# Or into a project venv
uv pip install dbga
dbga --version

# From source (development)
git clone https://github.com/niradler/dbga && cd dbga
uv sync --all-extras
uv run dbga --version
```

> [!NOTE]
> Distribution: `dbga` (PyPI) · CLI binary: `dbga` · Python import: `debug_agent`.

## Quick Tour

```sh
# Bounded execution + uniform JSON
dbga run --timeout 10 -- python script.py
dbga watch --cmd "python -m server" --pattern "READY" --until 1 --timeout 30

# Crash → triage in one call
dbga diagnose --timeout 20 -- python -m my_app
# → reruns paused at the deepest user frame, with full auto-context

# Reversible source probes (snapshot once, revert atomically)
dbga instrument add app.py:42 --kind log --code "print('items=', items, flush=True)"
dbga instrument list
dbga instrument revert --all

# Stateful DAP sessions
dbga session start --break-at "app.py:55:total == 0" -- script.py
dbga session eval --expr "items" --frame 1
dbga session continue --break loader.py:30 --remove-break app.py:55
dbga session restart
dbga session release

# VS Code collab — attach from your IDE
dbga session start --listen 5678 --use-bps-file -- script.py

# Debug a Go program — requires `dlv` on PATH (go install github.com/go-delve/delve/cmd/dlv@latest)
dbga session start --break-at main.go:12 -- main.go
dbga diagnose --timeout 30 -- go run main.go

# Parse a Node.js V8 stack trace (vscode-js-debug install not required for `localize`)
dbga localize --lang node --file crash.txt
```

Language is auto-detected from the script extension (`.py` → python, `.go` → go,
`.js`/`.mjs`/`.cjs`/`.ts`/`.mts`/`.cts` → node).
Pass `--lang {python,go,node}` to force a specific adapter.

### Installing language toolchains

| Language | Required tool                   | Install                                                                                                                                                                                                                                                                                             |
| -------- | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python   | `debugpy` (bundled)             | `uv tool install dbga`                                                                                                                                                                                                                                                                              |
| Go       | `dlv` (delve) on PATH           | `go install github.com/go-delve/delve/cmd/dlv@latest`                                                                                                                                                                                                                                               |
| Node.js  | `node` + vscode-js-debug bundle | VS Code ships it as a built-in extension; otherwise extract the latest `js-debug-dap-vX.Y.Z.tar.gz` from <https://github.com/microsoft/vscode-js-debug/releases> into `~/.local/share/` (POSIX) or `%LOCALAPPDATA%` (Windows), or point `$DBGA_JS_DEBUG_SERVER` at an explicit `dapDebugServer.js`. |

Every command supports `--text` for human-readable output and `--pretty` for
indented JSON. For full flag references: `dbga <cmd> --help`.

## Architecture

```text
                stateless CLI (dbga)
                     │
                     │ length-prefixed JSON, 127.0.0.1:PORT
                     ▼
           background daemon  ◄── one per --session name
                     │
                     │ Debug Adapter Protocol (TCP)
                     ▼
             <lang> DAP adapter ── attaches to ─── debuggee
        (debugpy · Delve · vscode-js-debug)
```

The daemon owns the live DAP connection, breakpoint state, current frame, and
output buffer. The CLI is a one-shot client. State is persisted in
`./.debug-agent/` (configurable via `--cwd`) so the CLI and daemon can share
information across calls and survive restarts. It's **project-scoped by
design** — breakpoints and source snapshots reference files in *this* repo, so
they belong next to the code. Add `.debug-agent/` to your `.gitignore`:

```text
.debug-agent/
├── breakpoints.json          # shared with VS Code via --use-bps-file
├── instrumentation.json      # active probes + file snapshots
├── snapshots/                # original source preserved for atomic revert
└── sessions/
    └── <name>/
        ├── meta.json         # pid, control port, started_at
        ├── log.txt           # daemon stdout/stderr
        └── lock              # liveness marker
```

## The `debug-agent` Claude Code plugin

`plugin/` is a [Claude Code plugin](https://docs.claude.com/en/docs/claude-code)
that bundles `dbga` with a full design → develop → debug → verify → clean-up
workflow for Python, Go, and Node/TypeScript:

- **Skills** (`/debug-agent:*`): `debug-agent` (the evidence-first `dbga` driver),
  plus `python`, `go`, `node` development skills that route to language-specific
  references on demand.
- **Agents** (`/agents`): `architect` (orchestrator) and `python-expert`,
  `go-expert`, `node-expert`.
- **Command:** `/debug-agent:setup` — optional one-shot `dbga` installer.

Full plugin docs: [`plugin/README.md`](plugin/README.md).

### Install — full plugin (recommended)

```sh
claude plugin marketplace add niradler/dbga
/plugin install debug-agent@dbga
/debug-agent:setup            # optional: installs the dbga CLI
```

### Install — a single skill

The [`skills`](https://github.com/vercel-labs/skills) CLI installs any one skill
standalone (skills only — agents/commands come with the full plugin). Resolution
is automatic via the repo-root marketplace manifest; no `--full-depth` needed:

```sh
npx skills add niradler/dbga --skill python   # or: go | node | debug-agent
npx skills add niradler/dbga --list           # preview what's available
```

Manual install of just the debugger skill also works:

```sh
# Linux / macOS
cp -r plugin/skills/debug-agent ~/.claude/skills/

# Windows PowerShell
Copy-Item -Recurse plugin/skills/debug-agent $env:USERPROFILE\.claude\skills\
```

### What the `debug-agent` skill covers

- **`SKILL.md`** — when to trigger, decision tree, mindset
- **`references/workflow.md`** — the evidence-first loop
- **`references/log-monitoring.md`** — using `watch`
- **`references/localization.md`** — `localize` and `diagnose`
- **`references/instrumentation.md`** — reversible probes
- **`references/debugger.md`** — driving `session`
- **`references/vscode-collab.md`** — `--listen` + shared breakpoints
- **`references/advanced.md`** — hang / deadlock / concurrency / wolf-fence

## Development

```sh
uv sync --all-extras
uv run pytest -v                    # all tests
uv run pytest tests/unit -v         # fast unit tests only
uv run pytest -m "not e2e" -v       # skip slowest CLI subprocess tests
uv run ruff check .                 # lint
uv run ruff format --check .        # format check
uv run mypy src                     # strict type check
uv run pytest --cov=debug_agent --cov-report=html
```

Tiers:

- **Unit tests** (`tests/unit/`) — pure functions only, no debugpy.
- **Integration** (`tests/integration/`, marked `integration`) — spawn the
  real `debugpy` adapter, drive DAP, no subprocess CLI.
- **E2E** (`tests/e2e/`, marked `e2e`) — invoke `python -m debug_agent ...` via
  subprocess. Slowest.

## Security Posture

- Control socket and `debugpy.listen` socket bind to `127.0.0.1` only — never
  `0.0.0.0`. No remote attach over the network is supported by design.
- `instrument add` refuses targets outside `--cwd` unless explicitly allowed.
- The daemon has an idle-timeout watchdog (default 1800s) so a forgotten
  session can't linger indefinitely.

## Status

Alpha. The CLI surface is stabilizing; JSON response shapes will follow
SemVer once `1.0.0` ships. Until then, breaking changes are documented in
`CHANGELOG.md`.

## License

[MIT](LICENSE).
