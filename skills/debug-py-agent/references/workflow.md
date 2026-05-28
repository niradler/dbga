# Workflow — The Evidence-First Loop

This is the canonical loop. Run it in order. If you skip a step, you're guessing.

## The Loop

```
1. Observe       — capture the failure deterministically
2. Localize      — point at a specific file:line
3. Hypothesize   — "I believe X because Y." Falsifiable.
4. Probe         — set a breakpoint, instrument, or eval. Pick the least invasive tool that can falsify the theory.
5. Compare       — observed vs expected at that point
6. If wrong location, return to (3). If two hypotheses fail at the same point, return to (1) — your model is wrong.
7. Verify        — eval the fix expression against live state. Apply. Restart. Confirm at the same breakpoint.
```

Two strikes, rethink: failing twice at the same location means your *theory* is wrong, not your probe. Re-read the code with fresh eyes before adding a third breakpoint.

## Phase-by-Phase

### 1. Observe — make it reproducible

Capture the failure under a bounded run:

```powershell
debug-cli run --timeout 30 -- python -m my_app --flag
```

Output (JSON):

```json
{
  "status": "ok",
  "exit_code": 1,
  "duration_seconds": 0.42,
  "stdout": "...",
  "stderr": "Traceback (most recent call last):\n  File \"...\", line 17, in main\n    ...\nValueError: bad input"
}
```

If the failure is in a log file or only appears in noisy stdout, switch to `watch` (see `log-monitoring.md`).

If the program *hangs*, see `advanced.md` (hang/deadlock).

### 2. Localize — point at a file:line

If `run` produced a traceback, send it straight to `diagnose` (rerun + pause):

```powershell
debug-cli diagnose --timeout 20 -- python -m my_app --flag
```

Or parse only, no rerun:

```powershell
debug-cli localize --file traceback.txt --context-lines 5
```

You get the deepest *user* frame (site-packages skipped) with surrounding source — that's where to point probe #1.

See `localization.md` for chained exceptions, SyntaxErrors, pytest output.

### 3. Hypothesize — falsifiable

State the theory in one sentence: *"I believe `items` is empty at `worker.py:55` because the upstream filter dropped all rows."* A good hypothesis names a specific value at a specific location, and the next observation will confirm or kill it.

No hypothesis yet? Bisect: set two breakpoints around the suspect region, run, then halve. Wolf-fence pattern: see `advanced.md`.

### 4. Probe — pick the least invasive tool

| Symptom | Tool |
|---|---|
| Single suspect point, you can pause | `session set-bp` + `continue` |
| Loop, only iteration N matters | conditional bp: `--break "f:42:i == 100"` |
| Long-running run, pausing is costly | `instrument add --kind log` |
| Non-Python failure (log line, child stderr) | `watch` |
| You already crashed | `diagnose` (one-shot) |

See `debugger.md` for session usage, `instrumentation.md` for probes, `log-monitoring.md` for watch.

### 5. Compare — observed vs expected

At every stop, ask:

- Do the **local variables** have the values I expected?
- Is the **call stack** showing the code path I expected?
- Does the **output so far** reveal anything unexpected?
- Are there **warnings** (e.g. breakpoint moved by adapter)?

Auto-context gives you all of this in the JSON response. Example response shape:

```json
{
  "status": "stopped",
  "reason": "breakpoint",
  "location": {"file": "worker.py", "line": 55, "function": "process"},
  "source": [
    {"line": 53, "text": "    for item in items:", "current": false},
    {"line": 54, "text": "        log.info('processing %s', item)", "current": false},
    {"line": 55, "text": "        result = transform(item)", "current": true},
    {"line": 56, "text": "        results.append(result)", "current": false}
  ],
  "locals": [{"name": "items", "type": "list", "value": "[]", "length": 0}],
  "stack": [
    {"frame_id": 1, "function": "process", "file": "worker.py", "line": 55},
    {"frame_id": 2, "function": "main",    "file": "app.py",    "line": 12}
  ],
  "output": "",
  "warnings": []
}
```

`items=[]` here is the smoking gun — root cause is upstream, in the caller. Step into frame 2 with `session eval --expr "items" --frame 2` or set a breakpoint at the data source.

### 6. Recurse or rethink

- **Probe killed the hypothesis (value was as expected)** → cause is elsewhere. Move the breakpoint to the next link upstream.
- **Probe confirmed the hypothesis** → you found *a* wrong value. Trace it up the stack to find where it *first* became wrong. That's the origin.
- **Two probes have failed at the same location** → your model of the code is wrong. Re-read the surrounding code from scratch, ignoring your prior theory. Often the bug is in a function you assumed was correct.

### 7. Verify — don't trust the fix until you've seen it work

While paused at the bug, write the proposed fix as an expression and eval it:

```powershell
debug-cli session eval --expr "transform(items) if items else None"
```

If that returns the expected value against live state, the fix will hold in code. Apply the edit, then:

```powershell
debug-cli session restart
debug-cli session continue       # to the same breakpoint
```

`restart` re-launches with the same args and preserves breakpoints. Confirm correct behavior at the same point where you originally found the bug. Then `release`.

## Walkthrough — End-to-End

**Bug: `compute()` returns `None` on some inputs.**

```powershell
# 1. Observe — reproduce
debug-cli run --timeout 5 -- python -c "from app import compute; print(compute([]))"
# → stdout: "None"

# 2. Localize — no traceback, so go straight to a session at the suspect line
debug-cli session start --break-at app.py:41 -- app.py
# → stops at app.py:41, locals: result=None, items=[]

# 3. Hypothesize — caller passed empty list

# 4. Probe — eval up the stack
debug-cli session eval --expr "items" --frame 1
# → "[]"  ← confirmed

# 5. Compare — yes, caller (app.py:10) loads from config and gets []

# 6. Move probe to data source
debug-cli session continue --break app.py:8 --remove-break app.py:41
# → stopped at app.py:8, config_path="/tmp/empty.yaml" — file is empty

# 7. Verify the fix
debug-cli session eval --expr "load_config('/tmp/empty.yaml') or default_config()"
# → {...sensible defaults...}
# Apply edit (add `or default_config()` to line 8), then:
debug-cli session restart
debug-cli session continue
# → exits 0, prints expected output

debug-cli session release
```

Five commands. No prints added. No restarts blind.

## Anti-patterns

- **Stepping forever.** Three steps in a row = you need a breakpoint deeper, not more steps.
- **Inspecting the symptom.** Don't set a breakpoint where the exception is raised — set it where the wrong value was first computed.
- **Breaking inside library code.** Break at the call site instead. You don't debug `json.loads` — you debug the input you're feeding it.
- **Unconditional breakpoints in tight loops.** Always use a condition (`--break "f:42:i == N"`) or you'll be hitting `continue` 999 times.
- **Side-effectful eval.** `eval --expr "queue.pop()"` mutates state. The next observation is now untrustworthy.
- **Trusting a fix you haven't observed.** Always restart and confirm at the same breakpoint.
