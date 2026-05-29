# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`dbga` (distribution) / `debug_agent` (import name) — an evidence-first **Python** debugger CLI built on top of `debugpy`/DAP. The CLI surface is stateless; a per-session background daemon owns the live DAP connection. Every stop returns auto-contextualized JSON (location, source window, locals, full stack, recent output, warnings) so an AI agent can drive a real debugger one command at a time.

Status: alpha. Python-only by design today — `debugpy` and `"type": "python"` are hardcoded in the launch path.

## Commands

Toolchain is **uv** + **ruff** + **mypy (strict)** + **pytest**.

```sh
uv sync --all-extras                       # install deps incl. dev
uv run dbga --version                      # run the CLI from source
uv run pytest -v                           # all tests
uv run pytest tests/unit -v                # fast unit tests
uv run pytest -m "not e2e" -v              # skip slow subprocess-CLI tests
uv run pytest -m integration -v            # only DAP-spawning tests
uv run pytest tests/unit/test_foo.py::test_x -v   # single test
uv run pytest --cov=debug_agent --cov-report=html # coverage
uv run ruff check .                        # lint
uv run ruff format .                       # format (or --check for CI)
uv run mypy src                            # strict type check (src only)
```

Test tiers (markers in `pyproject.toml`):

- **unit** (`tests/unit/`) — pure functions, no debugpy.
- **integration** (`tests/integration/`, `@pytest.mark.integration`) — spawn the real `debugpy` adapter and drive DAP directly, **no** subprocess CLI.
- **e2e** (`tests/e2e/`, `@pytest.mark.e2e`) — invoke `python -m debug_agent ...` via subprocess. Slowest tier.

## Architecture — the big picture

```text
stateless CLI (dbga)  ──framed JSON──►  per-session daemon  ──DAP/TCP──►  <lang> DAP adapter  ──spawns──►  debuggee
```

Three layers, each with a strict boundary:

1. **CLI (`cli.py`, `commands/*`)** — one-shot client. Parses args, talks to a daemon over a length-prefixed JSON socket, emits a single JSON (or `--text`/`--pretty`) result, exits. Holds no debugger state.
2. **Session daemon (`core/session_proc.py`)** — `python -m debug_agent.core.session_proc <meta_path>` started detached by `session start`. Owns one `DapSession`, listens on `127.0.0.1:<port>` for control requests (framed by `core/control_proto.py`), dispatches them against the session, runs an idle watchdog. One daemon per `--session NAME`.
3. **DAP layer (`core/dap_client.py`, `core/dap_session.py`, `adapters/`)** — `DapSession` is the language-agnostic state machine (`new → starting → running ⇄ stopped → terminated → released`); `DapClient` is the low-level DAP request/event plumbing; the `adapters/` package holds one concrete `Adapter` per language (currently `python.py` driving `debugpy.adapter`).
   - **Adding a language** means subclassing `adapters.base.Adapter`, registering it in `adapters/__init__.py::_REGISTRY`, and implementing `spawn_adapter`, `launch_payload`, and `parse_traceback`. Optional: `spawn_listen_mode` for IDE attach, `resolve_launch_target` override, `probe_template` for instrument defaults.
   - The CLI takes `--lang` on every multi-language command (`session start`, `localize`, `diagnose`); when absent, the language is auto-detected from the script extension (PythonAdapter claims `.py`).
   - **Standalone-adapter pattern is non-negotiable for Python.** We tried `python -m debugpy --listen ...` first and it hangs on `Waiting for adapter endpoints...` in debugpy 1.8.20 — see the docstring in `adapters/python.py`. Don't switch back.

### Cross-cutting modules to understand

- **`core/auto_context.py`** — builds the `StoppedContext` payload on every stop. The reason auto-context exists at all: each round-trip is expensive for an agent, so one stop returns location + source window + locals + stack + recent output + warnings in a single response.
- **`core/dap_types.py`** — the schemas that cross the daemon↔CLI boundary. Treat these as the public JSON contract; bumping them is a versioned change.
- **`core/control_proto.py`** — `[4-byte BE length][UTF-8 JSON]` framing. One req → one resp, no events, no pipelining.
- **DAP reverse requests** — `DapClient.register_reverse_handler(command, handler)` registers a Python callable that runs when the DAP server sends us a `type: "request"`. `DapSession` registers `startDebugging` so vscode-js-debug's child-session delegation works transparently: every `launch` spawns a child connection to the same `dapDebugServer.js`, and `wait_for_stop` polls parent + every child until one of them emits an event. The handler runs on the parent's reader thread and must only do I/O against the new (child) connection — never against the parent — to avoid reader-thread deadlock.
- **`core/process.py`** — `kill_tree` + Windows `creationflags` helpers. The DAP adapter is a parent; the debuggee is its child. On Windows we deliberately do **not** set `CREATE_NEW_PROCESS_GROUP` (triggers a thread-init race in debugpy under concurrent launches); tear-down walks the tree via `taskkill /F /T`. POSIX uses `start_new_session` + `killpg`.
- **`core/state.py`** — persistence under `.debug-agent/` (`breakpoints.json`, `instrumentation.json`, `snapshots/`, `sessions/<name>/`). `breakpoints.json` is the shared-with-VS-Code file when `--use-bps-file` is set.
- **`core/instrumentation.py` + `commands/instrument.py`** — reversible source probes. Adds Python source (log/assert lines) at given file:line, snapshotting the original to `.debug-agent/snapshots/` so `revert --all` is atomic. Refuses targets outside `--cwd` unless explicitly allowed.
- **`core/tracebacks.py` + `commands/localize.py`/`diagnose.py`** — Python-traceback parsing. `diagnose` is "crash → paused at deepest user frame in one call".
- **`core/watch.py` + `commands/watch.py`** — bounded-execution log scanner (`--pattern`, `--until N`).

### Output contract

Every CLI command returns a single JSON object on stdout via `core/format.emit_payload` / `emit_error`. The top-level `main()` in `cli.py` catches `KeyboardInterrupt` → `{"status": "interrupted"}` (exit 130), `OSError` → `io_error`, everything else → `internal` with traceback. New commands MUST go through `emit_payload`/`emit_error` so `--text` and `--pretty` work uniformly.

## Conventions

- **Strict typing.** `mypy --strict` runs over `src/` and is enforced. New code must satisfy it; don't add `# type: ignore` without a `[reason]` tag.
- **Ruff selects** `E, F, I, UP, B, SIM`; line length 100; target `py310`.
- **Sockets bind to `127.0.0.1` only** — both the control socket and `debugpy.listen`. Never `0.0.0.0`. No remote attach over the network by design.
- **`instrument add`** must keep the snapshot-then-modify ordering: the snapshot is the only thing that lets `revert` be atomic.
- **Tear-down is best-effort and idempotent.** `DapSession.release()` is called from `finally`. Tree-killing the adapter is the unconditional fallback after a graceful `disconnect` request.
- **The daemon idle-timeout watchdog** (default 1800s) exists so a forgotten session can't linger forever — don't disable it without thinking about cleanup.

## The skill (`skills/debug-agent/`)

A Claude/agent skill ships in-repo at `skills/debug-agent/`. It documents the evidence-first workflow that the CLI is designed for (`SKILL.md` + `references/*.md`). If you change CLI command shapes or JSON schemas, audit the skill — it has concrete command examples that go stale silently.
