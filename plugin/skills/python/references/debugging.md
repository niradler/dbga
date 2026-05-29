# Python — debugging with `dbga`

Python-specific `dbga` recipes. The full evidence-first loop, mindset, and cross-language details live in the **`debug-agent`** skill and `_shared/evidence-first.md` — this file is only the Python deltas. Confirm the tool first: `dbga --version` (expect 0.1.0). Python needs no extra toolchain (debugpy is bundled); `.py` auto-detects `--lang python`.

## Crash → triage in one call

`diagnose` parses the traceback, reruns paused at the deepest user frame, and returns full context.

```powershell
dbga diagnose --timeout 30 --pretty -- python buggy.py
```

Returns `"status": "diagnosed"` with `error_type`, `message`, and `deepest_user_frame` (e.g. `ZeroDivisionError`, `"division by zero"`, frame `average` line 3) plus a live paused session.

> `diagnose` reuses session name `default`. A lingering `default` yields `{"status":"error","error_type":"session_exists",...}` — clear it with `dbga session release` first.

## Parse a traceback you already have (no rerun)

```powershell
dbga localize --lang python --file py_trace.txt
```

Same `error_type` / `message` / `deepest_user_frame` shape, without launching anything. Use when you have log output but not the live process.

## Live session — inspect state at the fault

`session start` takes a **script path**, not a shell command (no `python -m foo`). eval runs in Python and returns Python-formatted values.

```powershell
dbga session start --session py --break-at buggy.py:3 --pretty -- buggy.py
dbga session eval --session py --expr "nums"     # → {"result":"[10, 20, 30]"}
dbga session eval --session py --expr "total"    # → {"result":"60"}
dbga session continue --session py               # re-hits the breakpoint with new state
dbga session release --session py                # → {"status":"ok"}
```

Pause at program start instead of a breakpoint with `--stop-on-entry` (reason: `entry`).

## Python-specific tactics

- **Set the breakpoint where the value *first* goes wrong, not where it raises.** A `KeyError`/`AttributeError`/`TypeError` at line 80 usually originates upstream — walk the stack up to the frame where the bad value was produced.
- **Inspect, don't print.** `session eval --expr "type(x)"`, `"vars(obj)"`, `"len(items)"`, `"x.__dict__"` answer "what is this really?" without editing source. Keep eval read-only unless you're probing a fix.
- **async / coroutine bugs:** breakpoint inside the coroutine and eval across the `await` boundary — this is exactly where source-reading misleads (see `references/async-concurrency.md`).
- **Comprehensions / generators hiding a bug:** break on the line and eval the source iterable and a sample element before trusting the one-liner.

## Reversible source probes (Python-centric)

`instrument` adds log/assert lines at a `file:line`, snapshotting the original so `revert --all` is atomic. Use for hot loops or a long run where pausing is impractical; see the `debug-agent` skill's `instrumentation.md`. Probes are Python-centric today.

## Verify the fix at the original fault

While still paused at the bug, eval the fixed expression against live state:

```powershell
dbga session eval --session py --expr "<fixed-expression>"
```

If it evaluates correctly **there**, the fix holds in code. Don't declare done until you've observed correct behavior at the same breakpoint where the bug appeared (`_shared/evidence-first.md`).

## Cleanup

Always `dbga session release` when done — a finished debuggee does not tear the daemon down. `dbga sessions ls` lists live daemons; forgotten ones self-expire (~30 min). State persists under project-local `.debug-agent/` — add it to `.gitignore`.
