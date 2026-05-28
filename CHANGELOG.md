# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-28

Initial alpha release of `debug-cli` — an evidence-first Python debugger CLI
designed to be driven by AI coding agents and humans alike. Wraps `debugpy`
behind a stateless CLI plus a per-session background daemon, with auto-context
returned on every stop.

### Added

- **`debug-cli run`** — execute a command with a hard timeout, returns
  structured stdout/stderr/exit_code/duration JSON. Cross-platform tree-kill
  on timeout (Windows `taskkill /F /T`, POSIX `killpg + SIGTERM`).
- **`debug-cli watch`** — file scan (`--file`) and live cmd tail (`--cmd`)
  with multi-pattern regex matching, `--until N` match count, `--timeout`,
  and `--context-lines`.
- **`debug-cli localize`** — traceback parser. Handles standard tracebacks,
  chained exceptions, `SyntaxError`, and pytest short-form output. Reports
  the deepest user frame and attaches surrounding source context.
- **`debug-cli instrument`** — reversible source probes (`log`,
  `breakpoint`, `trace`, `custom`) with file-level snapshot/revert.
  `instrument list` and `instrument revert --all` provide safe undo.
- **`debug-cli session`** — stateful DAP sessions over a background daemon:
  `start`, `inspect`, `release`, `stop`, `eval`, `continue`, `step` (in / out
  / over), `pause`, `output`, `set-bp`, `clear-bp`, `list-bp`, `restart`.
  Multi-session support via `--session NAME`, idle-timeout watchdog,
  127.0.0.1-only control socket.
- **Conditional breakpoints** on `session start --break-at`,
  `session set-bp`, and `session continue --break` —
  `FILE:LINE:CONDITION` syntax.
- **Disposable breakpoints** via `session continue --to FILE:LINE`.
- **Exception filters** via `session continue --break-on-exception`
  (`raised`, `uncaught`).
- **`debug-cli sessions ls`** — list active sessions and clean up zombie
  daemons (PID no longer alive).
- **`debug-cli diagnose`** — run a command, parse its traceback on crash,
  and rerun under a session paused at the deepest user frame. One call from
  "I have a crash" to "paused at the bug with full context."
- **`--listen PORT`** on `session start` — spawn the debuggee in
  `debugpy.listen` mode for VS Code remote-attach. Returns `attach_url`.
- **Shared breakpoints file** — `--use-bps-file` reads
  `.debug-cli/breakpoints.json` into the initial set; `set-bp`/`clear-bp`
  write back unless `--no-write-bps-file`.
- **Uniform JSON error contract** — every command emits a consistent
  `{"status": "error", "error_type": ..., "message": ..., "details": ...}`
  shape on failure; `--text` toggles human-readable output; `--pretty`
  indents JSON.
- **Auto-context on every stop** — location, ±5 source lines, locals
  (truncated to 200-char strings / 5-item collection previews), full stack
  (capped at 20 frames), recent output, warnings. No follow-up calls
  needed. Configurable via `--context-lines`.
- **`debug-py-agent` skill** (`skills/debug-py-agent/`) — Claude/agent
  skill that drives `debug-cli` with evidence-first workflow, log
  monitoring, localization, instrumentation, debugger, VS Code collab, and
  advanced (hang/deadlock/wolf-fence/concurrency) reference docs.

### Security

- Control socket binds to `127.0.0.1` only — never `0.0.0.0`.
- `debugpy.listen` socket binds to `127.0.0.1` only.
- `instrument add` refuses targets outside `--cwd` unless
  `--allow-outside` is passed.

### Known Issues

- `--break-at` does not yet accept conditions with embedded `:` characters
  beyond what `str.rpartition(":")` can disambiguate. Use double quotes:
  `--break-at "f:42:i == 100"`.
- Per-thread switching is not yet exposed (workaround: use
  `faulthandler.dump_traceback()` via `instrument`).
- `diagnose --rerun` cannot recover a launchable target from `-m` / `-c`
  invocations; falls back to traceback-only output (`{"status": "crash",
  "note": "cannot rerun: ..."}`).
- `watch --cmd` enforces `--timeout` only between output lines. A
  perfectly silent child won't trip the wall-clock until it prints
  something or exits. `kill_tree` on the cleanup path still ensures the
  child is torn down on exit; the symptom is a delayed return, not a
  leaked process.
- `session start --listen` does not register a `meta.json` entry, so
  `sessions ls` / `session release` cannot see or stop a listen-mode
  session. Use the process owner (or the VS Code attach UI) to terminate.
