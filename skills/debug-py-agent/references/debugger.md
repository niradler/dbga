# Debugger — `debug-cli session`

A `session` is a long-lived background debugpy daemon (one per `--session NAME`) that owns a single DAP connection to one Python process. The CLI is stateless: every command opens a localhost TCP control socket to the daemon, sends a length-prefixed JSON request, and prints the JSON response. State (current frame, breakpoints, last stop) lives in the daemon.

This is the workhorse for any interactive Python debugging: pausing, inspecting, stepping, evaluating, restarting, swapping breakpoints mid-run. Everything else in the skill exists to feed this loop or to handle cases where this loop is too expensive.

## Lifecycle

```powershell
# Start (stops at entry by default; --break-at to land deeper)
debug-cli session start --break-at app.py:42 -- script.py arg1 arg2

# Inspect / drive
debug-cli session inspect           # re-read current stop without stepping
debug-cli session eval --expr "len(items)"
debug-cli session step --mode over  # in | out | over
debug-cli session continue
debug-cli session pause             # interrupt a running debuggee
debug-cli session output            # drain stdout/stderr without stepping

# Breakpoints
debug-cli session set-bp app.py:50
debug-cli session set-bp "app.py:50:i == 100"        # conditional
debug-cli session clear-bp app.py:50
debug-cli session list-bp

# Restart + release
debug-cli session restart
debug-cli session release           # alias: stop
```

Default session name is `"default"`. To run multiple concurrent sessions:

```powershell
debug-cli session start --session frontend -- src/web.py
debug-cli session start --session backend  -- src/api.py
```

Each call to a non-`start` subcommand must pass `--session <name>` to address the right daemon. Daemons auto-exit on debuggee termination or after `--idle-timeout` seconds of inactivity (default 1800s = 30 min).

## What Every Stop Returns

Every command that *can* stop the program (`start`, `continue`, `step`, `pause`, `restart`) returns the same `StoppedContext` shape — no follow-up `inspect`/`where`/`list` calls needed:

```json
{
  "status": "stopped",
  "reason": "breakpoint",       // entry | breakpoint | step | pause | exception
  "session_id": "default",
  "location": {"file": "app.py", "line": 42, "function": "process"},
  "source": [
    {"line": 40, "text": "def process(items):",   "current": false},
    {"line": 41, "text": "    total = 0",         "current": false},
    {"line": 42, "text": "    for item in items:", "current": true},
    {"line": 43, "text": "        total += item.value", "current": false}
  ],
  "locals": [
    {"name": "items", "type": "list", "value": "[<Item ...>, <Item ...>]", "length": 12, "variables_reference": 7},
    {"name": "total", "type": "int",  "value": "0"}
  ],
  "stack": [
    {"frame_id": 1, "function": "process", "file": "app.py", "line": 42},
    {"frame_id": 2, "function": "main",    "file": "app.py", "line": 10}
  ],
  "output": "",                  // stdout/stderr accumulated since last drain
  "warnings": []                 // e.g. "breakpoint at app.py:99 moved to line 100"
}
```

If the program exits before stopping:

```json
{"status": "terminated", "exit_code": 1, "output": "..."}
```

`--context-lines N` (on every command that returns a stop) controls how many source lines flank the current line. Default 5. Lower for terse output, higher when context matters.

## Evaluation

```powershell
debug-cli session eval --expr "user.profile.settings"
debug-cli session eval --expr "expected == actual"
debug-cli session eval --expr "items[0].name" --frame 2     # frame 2 = caller's caller
```

`--frame N` evaluates in the Nth stack frame (0 = current top). This is how you trace causation upward without leaving the breakpoint.

**Don't call side-effectful methods in `eval`.** `queue.pop()`, `cursor.next()`, `db.commit()` mutate the live program. Stick to reads. The only exception is testing a fix expression — but be aware you're now in a state that wouldn't have happened without the eval.

## Continue, with Surgery

```powershell
debug-cli session continue --break app.py:60 --remove-break app.py:42
debug-cli session continue --to app.py:88                   # disposable bp, auto-removed
debug-cli session continue --break-on-exception raised      # break on next raised exception
debug-cli session continue --break-on-exception uncaught    # break on next uncaught
```

`--to` is for "I just want to see what `x` looks like at line 88 once." Don't manually manage that breakpoint's lifecycle.

`--break-on-exception` works at the language level — every `raise` will pause. Use `uncaught` if your code raises and catches regularly and you only care about ones that escape.

## Stepping Rules

- `--mode over` — execute current line, stop at next line in this function
- `--mode in` — descend into the next function call on the current line
- `--mode out` — run to end of current function, stop in caller

If you find yourself stepping **more than 3 times in a row**, stop. Set a breakpoint deeper instead. Stepping is a microscope; breakpoints are a teleporter. You're wasting cycles.

## Restart

```powershell
debug-cli session restart
```

Re-launches the debuggee with the same script, args, and breakpoints. Counter is reset, state is gone — but you didn't have to retype anything. Perfect after an edit-and-verify cycle.

If the previous run crashed mid-launch (rare), `restart` may fail; the response will say `"status": "restart_failed"` with the error, and the session will be torn down cleanly. Start over with `session start`.

## Worked Example — Finding a Wrong Value

Suspect: `worker.process()` returns 0 sometimes. We want to know what `items` looks like when that happens.

```powershell
# Start, breakpoint where we suspect the wrong branch
debug-cli session start --break-at "worker.py:55:total == 0" -- python -m runner

# Stopped — read the stop context
# locals: items=[], total=0
# That's "wrong" — items is empty. Why?

# Look at the caller
debug-cli session eval --expr "items" --frame 1
# → returns []

# Look at the caller's caller
debug-cli session eval --expr "raw_records" --frame 2
# → "raw_records=[]"  ← origin: the loader returned an empty list

# Now we know where to actually look. Re-target.
debug-cli session continue --break loader.py:30 --remove-break worker.py:55
# → stopped at loader.py:30, locals: source_path='/data/2026-05-28.json', exists=False

# The data file doesn't exist for today. That's the bug.
# Verify the fix idea against live state:
debug-cli session eval --expr "fallback_loader(source_path)"
# → list of 12 records

# Apply edit, restart, confirm:
debug-cli session restart
debug-cli session continue
# → status: terminated, exit_code: 0, output shows expected results

debug-cli session release
```

Six commands. Most of the value came from `eval --frame N`, not from stepping.

## Worked Example — Conditional Breakpoint in a Loop

You suspect iteration 500 of a 1000-iteration loop misbehaves:

```powershell
debug-cli session start --break-at "process.py:42:i == 500" -- python -m proc
# → stopped exactly at i=500. No 499 continues.
debug-cli session eval --expr "state.snapshot()"
debug-cli session step --mode over
debug-cli session step --mode over
debug-cli session step --mode over
# ↑ three steps. If you need a fourth, set a deeper breakpoint instead.
```

For loop bisection (you don't know which iteration), see `advanced.md` (wolf-fence).

## Listing Sessions

```powershell
debug-cli sessions ls
```

Returns active session names, their PIDs, control ports, idle timeouts, and zombie status. Zombies (sessions whose daemon PID no longer exists) are auto-removed by this command.

## Common Pitfalls

- **Breakpoint on a blank line / comment** → debugpy will slide it to the next executable line and emit a warning. Check `warnings[]` in the response.
- **Conditional breakpoint with bad syntax** → fails silently (the bp is set but never matches because the condition raises every iteration). Test the condition with `eval` first.
- **Forgetting to `release`** → daemon auto-exits after idle timeout, but until then it holds a localhost TCP port. Cheap, but not free. Always release when done.
- **Two `session start` calls with the same name** → the second one returns `"error": "session already running"`. Use `--session OTHER` or release the first.
