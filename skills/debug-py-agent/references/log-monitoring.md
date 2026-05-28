# Log Monitoring — `debug-cli watch`

Use `watch` when the failure shows up as text rather than as a Python exception: log lines, child-process stderr, a readiness banner you need to wait for, a noisy run where you want the error lines only.

It has two modes:

- **File mode** (`--file`) — scan a file once, top to bottom, return all matches. No process launched.
- **Cmd mode** (`--cmd`) — run a command, tail its combined stdout/stderr, stop when N matches are hit or the wall-clock timeout expires.

## File Mode — One-Shot Scan

```powershell
debug-cli watch --file logs/app.log --pattern "ERROR|Traceback"
```

Response:

```json
{
  "status": "ok",
  "source": "logs/app.log",
  "matches": [
    {"line": 142, "pattern": "ERROR|Traceback", "text": "ERROR config not found", "context": ["...","..."]},
    {"line": 198, "pattern": "ERROR|Traceback", "text": "Traceback (most recent call last):", "context": ["...","..."]}
  ]
}
```

`--pattern` is repeatable — pass it twice to look for different signals in one scan. Each match notes which pattern fired.

`--context-lines N` includes N lines on each side of the match. Useful for tracebacks where the interesting line is one or two before/after the match.

### When to use file mode

- Post-mortem on an already-failed run
- Filtering a multi-megabyte log down to the failures
- CI logs grabbed from an artifact

### Worked example

You ran a long batch job, it exited non-zero, and the run log is 80MB:

```powershell
debug-cli watch --file batch_2026_05_28.log --pattern "ERROR" --pattern "Traceback" --context-lines 3
```

Response gives you every error line with its surrounding context — usually enough to point at the failing record without paging through 80MB. Then localize one of those tracebacks:

```powershell
# Save the traceback block to a file or pipe via --stdin
debug-cli localize --file traceback_snippet.txt
```

## Cmd Mode — Live Tail with Stop Condition

```powershell
debug-cli watch --cmd "python -m server" --pattern "Listening on" --until 1 --timeout 30
```

This launches the command, tails combined stdout+stderr in real time, and stops as soon as **1 match** is seen — or after 30s if not.

Response:

```json
{
  "status": "matched",
  "matches": [{"line": 7, "pattern": "Listening on", "text": "Listening on 127.0.0.1:8080"}],
  "exit_code": null,
  "duration_seconds": 1.4,
  "stdout_tail": ["...","...","Listening on 127.0.0.1:8080"]
}
```

If the timeout fires first: `"status": "timeout"`.

If the process exits before any match: `"status": "exited", "exit_code": N`.

### When to use cmd mode

- **Wait for readiness** — block until a server prints "Listening on" before kicking the next step
- **Catch the first error** — `--until 1 --pattern "ERROR"` stops the run on first failure
- **Bounded smoke test** — `--timeout 5` won't let a runaway process hang you

### Worked example — wait for server, then run client

```powershell
# Step 1: start the server and wait for its banner
debug-cli watch --cmd "python -m my.server" --pattern "READY" --until 1 --timeout 15

# Step 2: now run the client smoke test under a separate timeout
debug-cli run --timeout 10 -- python -m my.client
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
