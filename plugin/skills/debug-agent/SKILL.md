---
name: debug-agent
description: Evidence-first debugging for Python, Go, and Node.js/TypeScript — use when a program crashes, hangs, returns wrong output, or you need to inspect live runtime state. Drives the `dbga` tool (traceback localization, crash triage, stateful DAP sessions, log scanning, reversible source probes, VS Code collab).
---

# Debug — Evidence-First (Python · Go · Node.js)

Use when reading source alone cannot validate your theory and you need observed runtime evidence: a crash, a hang, wrong output, a flaky test, a value that "shouldn't be possible." Reach for this skill _before_ you sprinkle prints or guess at fixes.

This skill drives `dbga` (version 0.1.1) — a stateless CLI on top of a background daemon that owns one stateful DAP session per name. The same evidence-first workflow spans three languages over DAP: **Python** (debugpy), **Go** (Delve), and **Node.js/TypeScript** (vscode-js-debug). Every execution command returns full auto-context (location + source + locals + stack + recent output + warnings) as structured JSON, so a single call gives you what a print-debugging loop normally costs five round-trips to learn.

## Languages

`--lang {python,go,node}` is accepted by `session start`, `localize`, and `diagnose`. When omitted, the language is auto-detected from the script's file extension.

| `--lang` | Toolchain prerequisite           | Install                                                                                                                                                                                               | Auto-detected extensions      |
| -------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| `python` | debugpy (bundled)                | — works out of the box                                                                                                                                                                                | `.py`                         |
| `go`     | Delve (`dlv`) on PATH            | `go install github.com/go-delve/delve/cmd/dlv@latest`                                                                                                                                                 | `.go`                         |
| `node`   | `node` on PATH + vscode-js-debug | not on npm — VS Code bundles it; else extract `js-debug-dap-vX.Y.Z.tar.gz` from the [vscode-js-debug releases](https://github.com/microsoft/vscode-js-debug/releases), or set `$DBGA_JS_DEBUG_SERVER` | `.js .mjs .cjs .ts .mts .cts` |

vscode-js-debug discovery order: `$DBGA_JS_DEBUG_SERVER` → VS Code / Cursor / Insiders extension dirs → manual extract at `~/.local/share/js-debug` (POSIX) or `%LOCALAPPDATA%\js-debug` (Windows).

## Prerequisites

```powershell
dbga --version            # expect 0.1.1+
```

Python needs nothing extra (debugpy is bundled). Go and Node need their toolchain as listed in the Languages table — install only the ones you'll debug. All commands below assume `dbga` is on PATH.

For deep CLI details and JSON schemas: `dbga <cmd> --help`.

## Decision Tree — Pick Your First Move

```
Got a crash with a traceback?            → diagnose       (references/localization.md)
Have a traceback text, no live process?  → localize       (references/localization.md)
Need to pause/inspect/step live?         → session        (references/debugger.md)
Got a log file or noisy stdout?          → watch          (references/log-monitoring.md)
Need a non-stop probe (loop / hot path)? → instrument     (references/instrumentation.md)
Pairing with a human at VS Code?         → references/vscode-collab.md
Hang / deadlock / concurrency / loop?    → references/advanced.md
Debugging Go or Node, not Python?        → add --lang go|node (or rely on extension auto-detect)
```

When in doubt, start with the **least invasive** tool that can falsify your current hypothesis. `references/workflow.md` is the canonical loop — read it once per debugging session.

## Core Commands

The blocks below use only verified command shapes. `watch`, `instrument`, `run`, stepping, and VS Code `--listen` collab are documented in the reference files linked from the Decision Tree — read those before invoking them.

### Crash → triage in one call

`diagnose` parses the crash, then reruns the program paused at the deepest user frame with full context.

```powershell
# Python (.py → python auto-detected)
dbga diagnose --timeout 30 --pretty -- python buggy.py

# Go (.go → go); needs --cwd for the module dir
dbga diagnose --lang go --timeout 60 --cwd <dir> --pretty -- go run buggy.go

# Node (.js → node)
dbga diagnose --timeout 60 --cwd <dir> -- node buggy.js
```

A successful diagnose returns `"status": "diagnosed"` with `error_type`, `message`, and a `deepest_user_frame`, plus a paused rerun session. Examples observed:

- Python: `error_type: "ZeroDivisionError"`, `message: "division by zero"`, deepest frame `average` line 3.
- Go: `error_type: "panic"`, `message: "runtime error: integer divide by zero"`, deepest frame `main.average` line 10. (File paths are forward-slash even on Windows.)
- Node: `error_type: "TypeError"`, `message: "Cannot read properties of null (reading 'value')"`, deepest frame `main` line 10. (`node:internal/*` frames are marked `is_user_code: false`.)

> `diagnose` reuses the session name `default`. If a previous `default` session is still alive you'll get `{"status":"error","error_type":"session_exists",...}` — clear it with `dbga session release` (default session) first.

### Parse a traceback only (no rerun)

```powershell
dbga localize --lang python --file py_trace.txt
dbga localize --lang go --file go_trace.txt
dbga localize --lang node --file node_trace.txt
```

Returns the same `error_type` / `message` / `deepest_user_frame` shape as `diagnose`, without launching the program.

### Stateful DAP session

`session start` takes a **script path** (not a shell command — no `python -m foo`). Default session name is `default`; pass `--session NAME` to run several at once. Session ops (`eval`, `continue`, `set-bp`, `list-bp`, `release`) behave identically across all three languages.

```powershell
# Start paused at a breakpoint
dbga session start --session py-demo --break-at buggy.py:3 --pretty -- buggy.py
# Go: dbga session start --session go-demo --cwd <dir> --break-at buggy.go:10 --pretty -- buggy.go
# Node: dbga session start --session node-demo --cwd <dir> --break-at buggy.js:3 --pretty -- buggy.js

# Inspect live state (eval runs in the TARGET language, with that language's formatting)
dbga session eval --session py-demo --expr "nums"      # Python → {"result":"[10, 20, 30]"}
dbga session eval --session py-demo --expr "total"     #        → {"result":"60"}

# Resume — re-hits the breakpoint with new state
dbga session continue --session py-demo

# Done
dbga session release --session py-demo                 # → {"status":"ok"}
```

You can also pause at program start instead of a breakpoint:

```powershell
dbga session start --session n --stop-on-entry --pretty -- buggy.js   # reason: entry
```

**eval runs in the target language.** Same variable, three formattings:

- Python `nums` → `[10, 20, 30]`
- Go `nums` → `[]int len: 3, cap: 3, [10,20,30]` (Delve, Go syntax)
- Node `nums` → `(3) [10, 20, 30]` (vscode-js-debug, JS syntax)

## Honest Limits

- **Node validated path = a single launched process.** Worker-thread / `child_process` multi-process lifecycle is not yet validated.
- **eval is language-native.** Expressions are evaluated by the underlying adapter in the target language (Python by debugpy, Go by Delve, JS by vscode-js-debug), with that language's value formatting — see the three examples above.
- **`diagnose` reuses session `default`.** A lingering `default` session yields `session_exists` until released.
- **`instrument` source probes are Python-centric** — see `references/instrumentation.md`.

## The Mindset

- **Two strikes, rethink.** If two hypotheses fail at the same location, your mental model is wrong. Stop probing — re-read the code, form a _different_ theory aimed at a _different_ location.
- **Set breakpoints instead of prints.** When you feel the urge to print, set a breakpoint. You get full context for free; prints give you one value.
- **Set where the problem _begins_, not where it _manifests_.** An exception at line 80 usually starts upstream. Move the breakpoint earlier until you see the value first go wrong.
- **Mimic the user journey.** Set breakpoints along the path you _expect_ execution to take. If a function you expected to be called isn't, the bug is in the caller — not the function.
- **Trace causation up the stack.** A wrong value at the deepest frame? Walk up the stack until the frame where the value _first_ became wrong — that's the origin, not the symptom.
- **Avoid side-effectful eval.** `eval` mutates live state. Stick to read-only expressions unless you're intentionally probing a fix.
- **Evidence over inference.** A debugger lets you observe what _does_ happen, not what _should_. The gap is your bug.

## Verify Your Fix

While paused at the bug, use `session eval --expr "<fix-expression>"` against live state. If the expression evaluates correctly there, the fix will work in code. **Don't trust a fix until you've observed correct behavior at the same breakpoint where you found the bug.**

## Cleanup

Always `session release` when done — a debuggee finishing on its own does **not** tear the daemon down. One daemon per `--session NAME`. `dbga sessions ls` lists live daemons under the current `--cwd` and reaps dead-pid zombies (forgotten ones also self-expire via the idle watchdog, ~30 min). State persists in a project-local `.debug-agent/` dir — add it to the project's `.gitignore`.

## Workflow

The evidence-first loop, what to do at each stop, when to escalate — `references/workflow.md`. Read it before opening a session.
