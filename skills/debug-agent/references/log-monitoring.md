# Log Monitoring — `dbga watch`

Use `watch` when the failure shows up as text rather than as a Python exception: log lines, child-process stderr, a readiness banner you need to wait for, a noisy run where you want the error lines only.

It has two modes:

- **File mode** (`--file`) — scan a file once, top to bottom, return all matches. No process launched.
- **Cmd mode** (`--cmd`) — run a command, tail its combined stdout/stderr, stop when N matches are hit or the wall-clock timeout expires.

## File Mode — One-Shot Scan

```powershell
dbga watch --file logs/app.log --pattern "ERROR|Traceback"
```

Response:

```json
{
  "matches": [
    {"line_number": 142, "pattern": "ERROR|Traceback", "match": "ERROR config not found",
     "groups": [], "surrounding_lines": ["...", "ERROR config not found", "..."], "timestamp_ms": 0},
    {"line_number": 198, "pattern": "ERROR|Traceback", "match": "Traceback (most recent call last):",
     "groups": [], "surrounding_lines": ["...", "Traceback (most recent call last):", "..."], "timestamp_ms": 0}
  ],
  "timed_out": false
}
```

`--pattern` is repeatable — pass it twice to look for different signals in one scan. Each match notes which pattern fired in its `pattern` field.

`--context-lines N` includes N lines on each side of the match (default 1). Useful for tracebacks where the interesting line is one or two before/after the match.

### When to use file mode

- Post-mortem on an already-failed run
- Filtering a multi-megabyte log down to the failures
- CI logs grabbed from an artifact

### Worked example

You ran a long batch job, it exited non-zero, and the run log is 80MB:

```powershell
dbga watch --file batch_2026_05_28.log --pattern "ERROR" --pattern "Traceback" --context-lines 3
```

Response gives you every error line with its surrounding context — usually enough to point at the failing record without paging through 80MB. Then localize one of those tracebacks:

```powershell
# Save the traceback block to a file or pipe via --stdin
dbga localize --file traceback_snippet.txt
```

## Cmd Mode — Live Tail with Stop Condition

```powershell
dbga watch --cmd "python -m server" --pattern "Listening on" --until 1 --timeout 30
```

This launches the command, tails combined stdout+stderr in real time, and stops as soon as **1 match** is seen — or after 30s if not.

Response:

```json
{
  "matches": [
    {"line_number": 7, "pattern": "Listening on", "match": "Listening on 127.0.0.1:8080",
     "groups": [], "surrounding_lines": [...], "timestamp_ms": 1717000000123}
  ],
  "timed_out": false
}
```

If the timeout fires before `--until` is satisfied, `timed_out` flips to `true`. If the process exits before any match, the matches list is empty and `timed_out` is `false`.

> **Caveat:** `--timeout` is enforced only when the child emits output (or exits). A perfectly silent child won't trip the wall-clock until it prints something. Force the child to print a heartbeat (e.g. `python -u`) if you depend on the timeout firing on a silent process.

### When to use cmd mode

- **Wait for readiness** — block until a server prints "Listening on" before kicking the next step
- **Catch the first error** — `--until 1 --pattern "ERROR"` stops the run on first failure
- **Bounded smoke test** — `--timeout 5` won't let a runaway process hang you

### Worked example — wait for server, then run client

```powershell
# Step 1: start the server and wait for its banner
dbga watch --cmd "python -m my.server" --pattern "READY" --until 1 --timeout 15

# Step 2: now run the client smoke test under a separate timeout
dbga run --timeout 10 -- python client.py
```

The first call returns when the server is ready, the second call exercises it. Both have hard timeouts, so a stuck process can't wedge your loop.

> **Caveat:** cmd mode runs the command and leaves it running when it returns on a match. Manage the lifecycle yourself (separate `run` invocation, or `taskkill`/`kill` once you're done).

## Pattern Tips

- Patterns are **Python regex** (anchor with `^` / `$` if needed).
- Repeat `--pattern` for an OR-style scan with per-match attribution. Don't shove everything into a single regex if you want to know which signal fired.
- For case-insensitive: `--pattern "(?i)error"`.
- Watch out for ANSI color codes in TTY output — patterns may need `\x1b\[[0-9;]*m` allowance.

## When *not* to use `watch`

- You already have a Python traceback in hand → use `localize` directly.
- The failure is silent (wrong output but no log line) → use `session` instead.
- You need to *inspect* values at the failure point → use `session`, not `watch`.

`watch` finds *that* something happened. `session` tells you *why*.
