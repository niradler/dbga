---
name: debug-py-agent
description: Evidence-first debugging for Python — use when a Python program crashes, hangs, returns wrong output, or you need to inspect live runtime state. Drives the `debug-cli` tool (timeouts, log scanning, traceback localization, reversible source probes, stateful DAP sessions, VS Code collab).
---

# Debug Python — Evidence-First

Use when reading source alone cannot validate your theory and you need observed runtime evidence: a crash, a hang, wrong output, a flaky test, a value that "shouldn't be possible." Reach for this skill *before* you sprinkle prints or guess at fixes.

This skill drives `debug-cli` — a stateless CLI on top of a background daemon that owns one stateful debugpy session per name. Every execution command returns full auto-context (location + source + locals + stack + recent output + warnings) as structured JSON, so a single call gives you what a print-debugging loop normally costs five round-trips to learn.

## Prerequisites

```powershell
debug-cli --version            # expect 0.1.0+
```

If the command is missing, install from the repo (`uv pip install -e .` inside the `debug-cli/` source tree). All commands below assume `debug-cli` is on PATH.

For deep CLI details and JSON schemas: `debug-cli <cmd> --help`.

## Decision Tree — Pick Your First Move

```
Got a crash with a traceback?            → diagnose       (references/localization.md)
Got a log file or noisy stdout?          → watch          (references/log-monitoring.md)
Need to pause/inspect/step live?         → session        (references/debugger.md)
Need a non-stop probe (loop / hot path)? → instrument     (references/instrumentation.md)
Just need a bounded run with a timeout?  → run            (references/workflow.md)
Pairing with a human at VS Code?         → --listen mode  (references/vscode-collab.md)
Hang / deadlock / concurrency / loop?    → references/advanced.md
```

When in doubt, start with the **least invasive** tool that can falsify your current hypothesis. Always: `references/workflow.md` is the canonical loop — read it once per debugging session.

## Core Commands at a Glance

```powershell
# Bounded execution + uniform JSON (run/watch/diagnose take arbitrary commands)
debug-cli run --timeout 10 -- python script.py
debug-cli watch --file logs/app.log --pattern "ERROR|Traceback"
debug-cli watch --cmd "python app.py" --pattern "READY" --until 1 --timeout 30

# session start takes a script path (not a shell command — no `python -m foo`)

# Crash → triage in one call
debug-cli diagnose --timeout 20 -- python script.py             # parses traceback, reruns paused at deepest user frame
debug-cli localize --file traceback.txt                          # parse only (no rerun)

# Reversible source probes
debug-cli instrument add app.py:42 --kind log    --code "print('x=', x)"
debug-cli instrument add app.py:42 --kind breakpoint --code "breakpoint()"
debug-cli instrument list
debug-cli instrument revert --all

# Stateful DAP sessions (default session name = 'default')
debug-cli session start --break-at app.py:42 -- script.py
debug-cli session eval --expr "len(items)"
debug-cli session continue --break "app.py:50:len(items) == 0"
debug-cli session step --mode in            # in | out | over
debug-cli session set-bp app.py:42:condition
debug-cli session list-bp
debug-cli session restart
debug-cli session release                    # alias: stop

# VS Code collab — share breakpoints, attach
debug-cli session start --listen 5678 --use-bps-file -- script.py
debug-cli sessions ls
```

## The Mindset

- **Two strikes, rethink.** If two hypotheses fail at the same location, your mental model is wrong. Stop probing — re-read the code, form a *different* theory aimed at a *different* location.
- **Set breakpoints instead of prints.** When you feel the urge to print, set a breakpoint. You get full context for free; prints give you one value.
- **Set where the problem *begins*, not where it *manifests*.** An exception at line 80 usually starts upstream. Move the breakpoint earlier until you see the value first go wrong.
- **If you're stepping more than 3 times in a row, you need a breakpoint, not more steps.** Stepping is for the last few lines of a known suspect region.
- **Mimic the user journey.** Set breakpoints along the path you *expect* execution to take. If a function you expected to be called isn't, the bug is in the caller — not the function.
- **Trace causation up the stack.** A wrong value at frame 0? Run `session eval --expr "<var>" --frame 1` to see what the caller passed. Keep going up until the frame where the value *first* became wrong — that's the origin, not the symptom.
- **Avoid side-effectful eval.** `eval` mutates live state. Stick to read-only expressions unless you're intentionally probing a fix.
- **Evidence over inference.** A debugger lets you observe what *does* happen, not what *should*. The gap is your bug.

## What Makes `debug-cli` Different

These differentiators are the reason we don't fall back to `pdb` or raw `debugpy`:

1. **`diagnose`** — one call from "I have a crash" to "I'm paused at the deepest user frame with full context." Doesn't replace careful thought, but compresses the first 60 seconds.
2. **`instrument`** — reversible probes (`log`, `breakpoint`, `trace`, `custom`). Use when a session won't help (long-running jobs, prod-like reproductions, non-stop scenarios). `instrument revert --all` undoes everything atomically.
3. **`localize`** — parses tracebacks (including chained, syntax errors, pytest_short) into structured frames with source context. Pipe in any traceback; get back the deepest user frame.
4. **`watch`** — regex tail without a debugger attached. First move when the failure shows up in logs rather than as a Python exception.
5. **Shared breakpoints + `--listen`** — VS Code collab. Set breakpoints from the editor, run the session from your CLI; both consume the same `.debug-cli/breakpoints.json`.
6. **Auto-context everywhere.** No follow-up `inspect` or `where` calls needed. Every stop gives you the full picture in one JSON blob.

## Verify Your Fix

While paused at the bug, use `session eval --expr "<fix-expression>"` against live state. If the expression evaluates correctly there, the fix will work in code. Edit, then `session restart` — same args, same breakpoints, fast feedback loop. **Don't trust a fix until you've observed correct behavior at the same breakpoint where you found the bug.**

## Cleanup

Session daemons exit when you call `session release` (alias `stop`), or after the idle-timeout watchdog fires (default 1800s; override with `--idle-timeout` on `session start`). A debuggee that finishes on its own does **not** tear the daemon down — always `release` when you're done. If a daemon's PID disappears (process killed externally), `debug-cli sessions ls` cleans up the zombie meta on the next call.

## Workflow

The evidence-first loop, what to do at each stop, when to escalate — `references/workflow.md`. Read it before opening a session.

## Related Skills

- `superpowers:systematic-debugging` — the 4-phase debugging discipline this skill plugs into. If you haven't formed a hypothesis yet, start there.
