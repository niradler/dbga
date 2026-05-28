# Localization — `localize` and `diagnose`

When the program already crashed, your first job is to point at a *specific file and line* — the deepest user frame, where your code (not the framework, not site-packages) sits on top of the traceback. Two commands cover this:

- **`localize`** — parses a traceback into structured frames. No execution. Pure function.
- **`diagnose`** — runs the command, parses the traceback, reruns under a session paused at the deepest user frame. One call from "crash" to "paused at the bug."

Use `diagnose` for crashes you can re-trigger. Use `localize` when you only have the traceback text (CI log, error report, screenshot OCR).

## `localize` — Parse a Traceback

Input sources:

```powershell
debug-cli localize --file traceback.txt
debug-cli localize --stdin                            # piped
debug-cli localize "Traceback (most recent call last):..."   # positional
```

It handles:

- Standard tracebacks
- Chained exceptions (`During handling of the above exception, another exception occurred:` / `The above exception was the direct cause of the following exception:`)
- `SyntaxError` (no stack — just file:line + caret)
- pytest short-form output

Response:

```json
{
  "status": "ok",
  "exception_type": "ValueError",
  "exception_message": "bad input: ''",
  "frames": [
    {"file": "/site-packages/click/core.py", "line": 1042, "function": "invoke", "is_user": false},
    {"file": "app.py", "line": 17, "function": "main", "is_user": true,
     "source": [{"line": 15, "text": "..."}, {"line": 17, "text": "raise ValueError(...)", "current": true}]},
    {"file": "app.py", "line": 9, "function": "_parse", "is_user": true, "source": [...]}
  ],
  "deepest_user_frame": {"file": "app.py", "line": 17, "function": "main"}
}
```

**`deepest_user_frame` is what you point your first breakpoint at.** It's the deepest frame that doesn't live in site-packages or the stdlib.

### `--context-lines N`

Attach N source lines on each side of each user frame (default 5). Drop to 2-3 for terse output, up to 10 if you need broader context.

### Worked example — parse a CI failure

A CI run failed. You grabbed the traceback into `ci_fail.txt`:

```powershell
debug-cli localize --file ci_fail.txt --context-lines 3
```

You learn: `app.py:17` in `main()`, `ValueError: bad input: ''`. Now you can:

```powershell
debug-cli session start --break-at app.py:17 -- python -m app
debug-cli session eval --expr "raw_input"     # what was passed?
```

## `diagnose` — Crash → Paused, One Call

```powershell
debug-cli diagnose --timeout 20 -- python -m my_app
```

What it does:

1. Runs the command (with the supplied timeout, tree-killed if it hangs).
2. If the exit code is non-zero and stderr contains a parseable traceback, parses it.
3. By default (`--rerun`), spawns a session with a breakpoint at the deepest user frame and starts the program. You land paused there, with full auto-context.

Response (rerun=true, crash):

```json
{
  "status": "stopped",
  "reason": "breakpoint",
  "session_id": "default",
  "diagnosis": {
    "exception_type": "ValueError",
    "deepest_user_frame": {"file": "app.py", "line": 17, "function": "main"}
  },
  "location": {"file": "app.py", "line": 17, "function": "main"},
  "source": [...],
  "locals": [{"name": "raw_input", "type": "str", "value": "''"}],
  "stack": [...]
}
```

You can now `session eval`, `session step`, `session continue` against the live session named `default` (or whatever you passed via `--session`).

Response (no crash): just the run result, exit code 0.

Response (crash, but `--no-rerun`): the localize output, no session opened.

### When to use `diagnose`

- The first 60 seconds of any crash you can reproduce locally
- You don't yet have a hypothesis — start at the failure point and trace causation upward
- Quick "where in our code does this raise" check

### When *not* to use `diagnose`

- The failure is intermittent / can't be reproduced on demand — use `instrument` instead so the next natural occurrence is captured
- The crash is inside an external service / not your Python process — use `localize` on the captured traceback
- You need a specific breakpoint *before* the failure — `session start --break-at <earlier-line>`

### Worked example

```powershell
debug-cli diagnose --timeout 10 -- python script.py --input bad.json
# → status: stopped, paused at script.py:42 in load_config(), locals: path='bad.json', data=None

# That's the symptom. The bug is upstream — load_config returned None.
debug-cli session continue --to script.py:30          # disposable bp at the data source
# → stopped at script.py:30, locals: text='', f=<file>

# Now we see it: the file was opened but empty. The real bug is the upstream config-build step.
debug-cli session release
```

`diagnose` got you to the symptom in one call. From there it's the normal workflow loop.

## Edge Cases

- **SyntaxError** — no stack. `deepest_user_frame` is the file:line of the syntax error itself. `diagnose` will refuse to rerun (no useful breakpoint to set on a file that won't even parse) — you'll just get the localize payload.
- **`-m` / `-c` invocation** — `diagnose` can't always recover a launchable script target. If that happens you'll see `"rerun_skipped": "no launchable target"`; fall back to `localize` + a manual `session start`.
- **Tracebacks with mixed user + library frames** — the parser walks bottom-up and picks the deepest frame whose path doesn't contain `site-packages`, `/lib/python`, or `\Lib\`. If your project lives under a path that looks like a library, you may need to point breakpoints manually.
- **Chained exceptions** — the deepest user frame across *both* chains is selected. The `frames` array contains both chains with a `chain_marker` separator entry.
