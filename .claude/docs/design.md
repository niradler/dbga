# debug-cli — Base Design

Status: **draft for Nir's review**. Locked sections marked ✅.

## Purpose

Give an AI agent the concrete tools and methods to debug Python (later: JS) code
**by evidence, like a human at a debugger** — not by guessing from stack traces.

The agent should be able to:
- Run code under time/output control
- Tail logs and match patterns
- Parse tracebacks → localize the failing line
- Place reversible instrumentation (logs/breakpoints)
- Drive a real debugger: pause, inspect state, eval, step, continue
- Collaborate with a human in VS Code

## Two artifacts ✅

| Artifact | Lives in | Role |
|---|---|---|
| **`debug-cli`** (this repo) | `c:\Projects\debug-cli` | The execution layer. Python CLI the agent invokes. JS sibling later. |
| **`debug-py-agent` skill** | `~/.claude/skills/debug-py-agent/` | The teaching layer. Tells the agent when to use which command and how to reason. References this CLI. |

The existing `superpowers:systematic-debugging` skill is the **process** layer (RCA-first, 4 phases). Our skill is the **tooling** layer. They cross-reference; we don't duplicate.

## Locked design decisions ✅

1. **Architecture**: One CLI tool written in Python, invoked as `python -m debug_cli ...` (no compiled binary).
2. **Session model**: Stateful interactive debugger sessions, persisted across agent turns. Real-human workflow: start → run-to-bp → pause → agent inspects/reacts → continue → pause → ... → release.
3. **Debugger backend**: `debugpy` (Microsoft's official; same one VS Code uses). DAP protocol. JS sibling will use `vscode-js-debug` (also DAP) for command parity.
4. **VS Code collab modes**:
   - **Pattern 1** — agent honors any `breakpoint()` calls in source
   - **Pattern 2** — agent reads/writes `.debug-cli/breakpoints.json` (a shared file convention)
   - **Pattern 3** — `--listen <port>` attach mode: user can attach VS Code to the agent's debugpy session
5. **Output format**: JSON to stdout by default (agent-friendly). `--pretty` flag for human reading. Errors as structured JSON with `error_type` field, not just text.
6. **State location**: `<target-project>/.debug-cli/` per project, holding:
   - `sessions/<session_id>/` — one dir per active debug session (sockets, PID, frame snapshots, log)
   - `breakpoints.json` — the shared bps file
   - `instrumentation.json` — registry of injected probes (for clean revert)
   - `snapshots/` — pre-instrumentation file copies

## Proposed v1 CLI surface

```
debug-cli run <script> [--args ...] [--timeout SECS] [--cwd DIR] [--env K=V ...]
    Run a Python script with timeout. Returns JSON:
      { exit_code, duration_ms, timed_out, stdout, stderr, killed_signal }
    Stdout/stderr captured; --stream flag tails live to file instead.

debug-cli watch <file>|--cmd "<cmd>" --pattern <regex> [--until N] [--timeout SECS]
    Tail a file OR run a command and watch its output. Match a regex.
    Return list of matches as JSON: [{ line_number, timestamp, match, groups, surrounding_lines }]
    --until N: stop after N matches. --timeout: stop after SECS.

debug-cli localize <traceback>|--stdin|--file <path>
    Parse a Python traceback. Returns:
      { error_type, message,
        frames: [{file, line, func, code, is_user_code}],
        deepest_user_frame: {...},
        source_context: ["line 38: ...", "line 39: ...", ...] }

debug-cli instrument add <file>:<line> --code "<snippet>" [--type log|trace|breakpoint]
    Insert <snippet> at <file>:<line>. Snapshots original. Logs to instrumentation.json.
    Returns { instrumentation_id }.
debug-cli instrument list
    List active instrumentations.
debug-cli instrument revert [<id> | --all]
    Restore original source files. Clean.

debug-cli session start <script> [--args ...] [--break-at file:line ...]
                                  [--timeout SECS] [--listen PORT] [--use-bps-file]
    Launch <script> under debugpy as a background process. Set breakpoints from --break-at
    AND/OR from .debug-cli/breakpoints.json if --use-bps-file. If --listen, debugpy listens
    on PORT so VS Code can attach.
    Runs until first bp (or end). Returns:
      { session_id, status: "stopped"|"exited"|"error",
        reason, frame: {...}, locals: {...}, stack: [...] }

debug-cli session inspect <session_id> [--depth N]
    Returns current frame, locals, and call stack (up to N frames).

debug-cli session eval <session_id> --expr "<py expression>"
    Evaluates expression in the current frame's scope. Returns repr + type.

debug-cli session continue <session_id> [--timeout SECS]
    Resume. Returns next pause event (bp hit, exit, exception, or timeout).

debug-cli session step <session_id> --mode in|over|out
    Step. Returns new frame/locals.

debug-cli session set-bp <session_id> <file>:<line> [--condition "<expr>"]
debug-cli session list-bp <session_id>
debug-cli session clear-bp <session_id> <bp_id>

debug-cli session release <session_id>
    Terminate debuggee, clean up state.

debug-cli sessions ls
    List all active sessions across the project.
```

Out of v1 (defer):
- `repl` (persistent Python REPL session) — useful but not needed for the core debug loop
- `vscode sync-bps` (read VS Code's SQLite workspace state) — follow-up

## Killer convenience command (worth including in v1?)

```
debug-cli diagnose <command> [--timeout SECS]
    1. Run <command>
    2. If output contains a Python traceback, parse it
    3. Identify the deepest user frame
    4. Start a debug session with bp at that line (rerun)
    5. Return session_id ready for inspection
```

One call: "this is crashing — give me a debugger paused at the failure point." High value for agent workflows.

## Repo layout (proposed)

```
c:\Projects\debug-cli\
├── pyproject.toml
├── README.md
├── src/
│   └── debug_cli/
│       ├── __init__.py
│       ├── __main__.py         # python -m debug_cli
│       ├── cli.py              # argparse / typer dispatch
│       ├── commands/
│       │   ├── run.py
│       │   ├── watch.py
│       │   ├── localize.py
│       │   ├── instrument.py
│       │   ├── session.py
│       │   └── diagnose.py
│       ├── core/
│       │   ├── process.py      # subprocess + timeout + tree kill (Windows-safe)
│       │   ├── traceback.py    # parser
│       │   ├── instrumentation.py
│       │   ├── state.py        # .debug-cli/ I/O
│       │   └── dap_client.py   # talks to debugpy via DAP socket
│       └── adapters/
│           └── debugpy_adapter.py  # launches & manages debugpy bg process
├── tests/
│   ├── fixtures/               # broken python scripts to debug
│   ├── test_run.py
│   ├── test_watch.py
│   ├── test_localize.py
│   ├── test_instrument.py
│   └── test_session.py
└── .claude/
    └── docs/
        └── design.md           # this file
```

## Distribution

`pip install -e .` for now. `python -m debug_cli ...` is the canonical invocation. An optional `debug-cli` console script entry point in pyproject.toml so the agent can call it either way.

Python target: **3.10+** (for match statements, better error locations, pep 657).

## Things to validate by code, not reasoning (per nir-collab)

Before committing to designs, prove these work with a 10-line spike each:
- `debugpy` can be driven programmatically from another Python process via DAP, including: launch, set bp, run, hit bp, get locals, eval, continue, get next bp, release.
- Process-tree kill works on Windows (the timeout case — Python subprocesses with children).
- Traceback parser handles: regular tracebacks, chained exceptions (`__cause__`/`__context__`), syntax errors (different format), `pytest` short tracebacks.

## Open questions to resolve before scaffolding

1. **Diagnose command in v1?** — see "Killer convenience" above. My rec: yes, it pays for itself.
2. **Auto-discovery of sessions?** — `sessions ls` would scan `.debug-cli/sessions/`. Should also detect zombie sessions (PID dead) and clean them up. My rec: yes, simple, do it.
3. **Permission model for `instrument`?** — should agent be allowed to instrument any file by default, or only files under `--cwd`? My rec: default to cwd-only, `--allow-outside` flag to override. Prevents accidental damage to system files.
4. **Stdout discipline** — should ALL CLI output be one JSON line for parseability, or multi-line pretty JSON? My rec: pretty by default, `--ndjson` for streaming/parsing. Agents handle both fine.
