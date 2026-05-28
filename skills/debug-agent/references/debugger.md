# Debugger — `dbga session`

A `session` is a long-lived background debugpy daemon (one per `--session NAME`) that owns a single DAP connection to one Python process. The CLI is stateless: every command opens a localhost TCP control socket to the daemon, sends a length-prefixed JSON request, and prints the JSON response. State (current frame, breakpoints, last stop) lives in the daemon.

This is the workhorse for any interactive Python debugging: pausing, inspecting, stepping, evaluating, restarting, swapping breakpoints mid-run. Everything else in the skill exists to feed this loop or to handle cases where this loop is too expensive.

## Lifecycle

The positional after `--` is the **path to a Python script** (e.g. `script.py`), not a command line. The CLI launches it under debugpy directly — `python -m foo` and `python -c "..."` aren't supported here (use a script file instead).

```powershell
# Start (runs through to first breakpoint; pass --stop-on-entry to halt at first line)
dbga session start --break-at app.py:42 -- script.py arg1 arg2

# Inspect / drive
dbga session inspect           # re-read current stop without stepping
dbga session eval --expr "len(items)"
dbga session step --mode over  # in | out | over
dbga session continue
dbga session pause             # interrupt a running debuggee
dbga session output            # drain stdout/stderr without stepping

# Breakpoints
dbga session set-bp app.py:50
dbga session set-bp "app.py:50:i == 100"        # conditional
dbga session clear-bp app.py:50
dbga session list-bp

# Restart + release
dbga session restart
dbga session release           # alias: stop
```

Default session name is `"default"`. To run multiple concurrent sessions:

```powershell
dbga session start --session frontend -- src/web.py
dbga session start --session backend  -- src/api.py
```

Each call to a non-`start` subcommand must pass `--session <name>` to address the right daemon. Daemons exit when the debuggee terminates *and* `session release` is called, or after `--idle-timeout` seconds with no incoming requests (default 1800s = 30 min). A finished debuggee on its own does not tear the daemon down; you should always `release` when you're done.

## What Every Stop Returns

Every command that *can* stop the program (`start`, `continue`, `step`, `pause`, `restart`) returns the same `StoppedContext` shape — no follow-up `inspect`/`where`/`list` calls needed:

```json
{
  "status": "stopped",
  "reason": "breakpoint",
  "session_id": "default",
  "location": {"file": "app.py", "line": 42, "function": "process"},
  "source": [
    {"line": 40, "text": "def process(items):",   "current": false},
    {"line": 41, "text": "    total = 0",         "current": false},
    {"line": 42, "text": "    for item in items:", "current": true},
    {"line": 43, "text": "        total += item.value", "current": false}
  ],
  "locals": [
    {"name": "items", "type": "list", "value": "[<Item ...>, <Item ...>]",
     "variables_reference": 7, "length": 12},
    {"name": "total", "type": "int",  "value": "0", "variables_reference": 0}
  ],
  "stack": [
    {"frame_id": 1, "function": "process", "file": "app.py", "line": 42},
    {"frame_id": 2, "function": "main",    "file": "app.py", "line": 10}
  ],
  "output": "",
  "warnings": [],
  "exit_code": null
}
```

`reason` is one of `entry`, `breakpoint`, `step`, `pause`, `exception`. `warnings` carries adapter notices like "breakpoint at app.py:99 moved to line 100".

If the program exits before stopping (or after `continue` runs it to completion):

```json
{"status": "terminated", "reason": "", "session_id": "default", "exit_code": 1,
 "location": null, "source": [], "locals": [], "stack": [], "output": "...", "warnings": []}
```

`--context-lines N` (on every command that returns a stop) controls how many source lines flank the current line. Default 5. Lower for terse output, higher when context matters.

## Evaluation

```powershell
dbga session eval --expr "user.profile.settings"
dbga session eval --expr "expected == actual"
dbga session eval --expr "items[0].name" --frame 2     # frame 2 = caller's caller
```

`--frame N` evaluates in the Nth stack frame (0 = current top). This is how you trace causation upward without leaving the breakpoint.

**Don't call side-effectful methods in `eval`.** `queue.pop()`, `cursor.next()`, `db.commit()` mutate the live program. Stick to reads. The only exception is testing a fix expression — but be aware you're now in a state that wouldn't have happened without the eval.

## Continue, with Surgery

```powershell
dbga session continue --break app.py:60 --remove-break app.py:42
dbga session continue --to app.py:88                   # disposable bp, auto-removed
dbga session continue --break-on-exception raised      # break on next raised exception
dbga session continue --break-on-exception uncaught    # break on next uncaught
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
dbga session restart
```

Re-launches the debuggee with the same script, args, and breakpoints. Counter is reset, state is gone — but you didn't have to retype anything. Perfect after an edit-and-verify cycle.

If the relaunch fails, the structured error contract kicks in: you'll get `{"status": "error", "error_type": ..., "message": ..., "details": ...}` with the daemon's explanation. Inspect the message and start over with `session start`.

## Worked Example — Finding a Wrong Value

Suspect: `worker.process()` returns 0 sometimes. We want to know what `items` looks like when that happens.

```powershell
# Start, breakpoint where we suspect the wrong branch
dbga session start --break-at "worker.py:55:total == 0" -- runner.py

# Stopped — read the stop context
# locals: items=[], total=0
# That's "wrong" — items is empty. Why?

# Look at the caller
dbga session eval --expr "items" --frame 1
# → returns []

# Look at the caller's caller
dbga session eval --expr "raw_records" --frame 2
# → "raw_records=[]"  ← origin: the loader returned an empty list

# Now we know where to actually look. Re-target.
dbga session continue --break loader.py:30 --remove-break worker.py:55
# → stopped at loader.py:30, locals: source_path='/data/2026-05-28.json', exists=False

# The data file doesn't exist for today. That's the bug.
# Verify the fix idea against live state:
dbga session eval --expr "fallback_loader(source_path)"
# → list of 12 records

# Apply edit, restart, confirm:
dbga session restart
dbga session continue
# → status: terminated, exit_code: 0, output shows expected results

dbga session release
```

Six commands. Most of the value came from `eval --frame N`, not from stepping.

## Worked Example — Conditional Breakpoint in a Loop

You suspect iteration 500 of a 1000-iteration loop misbehaves:

```powershell
dbga session start --break-at "process.py:42:i == 500" -- proc.py
# → stopped exactly at i=500. No 499 continues.
dbga session eval --expr "state.snapshot()"
dbga session step --mode over
dbga session step --mode over
dbga session step --mode over
# ↑ three steps. If you need a fourth, set a deeper breakpoint instead.
```

For loop bisection (you don't know which iteration), see `advanced.md` (wolf-fence).

## Listing Sessions

```powershell
dbga sessions ls
```

Returns active session names, their PIDs, control ports, idle timeouts, and zombie status. Zombies (sessions whose daemon PID no longer exists) are auto-removed by this command.

## Common Pitfalls

- **Breakpoint on a blank line / comment** → debugpy will slide it to the next executable line and emit a warning. Check `warnings[]` in the response.
- **Conditional breakpoint with bad syntax** → fails silently (the bp is set but never matches because the condition raises every iteration). Test the condition with `eval` first.
- **Forgetting to `release`** → daemon auto-exits after idle timeout, but until then it holds a localhost TCP port. Cheap, but not free. Always release when done.
- **Two `session start` calls with the same name** → the second one returns `{"status":"error", "error_type":"session_exists", "message":"session 'default' already running (pid=...)"}`. Use `--session OTHER` or release the first.
