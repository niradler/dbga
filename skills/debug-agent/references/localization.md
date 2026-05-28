# Localization — `localize` and `diagnose`

When the program already crashed, your first job is to point at a *specific file and line* — the deepest user frame, where your code (not the framework, not site-packages) sits on top of the traceback. Two commands cover this:

- **`localize`** — parses a traceback into structured frames. No execution. Pure function.
- **`diagnose`** — runs the command, parses the traceback, reruns under a session paused at the deepest user frame. One call from "crash" to "paused at the bug."

Use `diagnose` for crashes you can re-trigger. Use `localize` when you only have the traceback text (CI log, error report, screenshot OCR).

## `localize` — Parse a Traceback

Input sources:

```powershell
dbga localize --file traceback.txt
dbga localize --stdin                            # piped
dbga localize "Traceback (most recent call last):..."   # positional
```

It handles:

- Standard tracebacks
- Chained exceptions (`During handling of the above exception, another exception occurred:` / `The above exception was the direct cause of the following exception:`)
- `SyntaxError` (no stack — just file:line + caret)
- pytest short-form output

Response:

```json
{
  "error_type": "ValueError",
  "message": "bad input: ''",
  "frames": [
    {"file": "/site-packages/click/core.py", "line": 1042, "func": "invoke",
     "code": "return self.callback(**ctx.params)", "is_user_code": false, "code_context": []},
    {"file": "app.py", "line": 17, "func": "main",
     "code": "raise ValueError(repr(raw_input))", "is_user_code": true,
     "code_context": ["def main():", "    raw_input = sys.argv[1]", "    raise ValueError(repr(raw_input))"]}
  ],
  "deepest_user_frame": {"file": "app.py", "line": 17, "func": "main",
                          "code": "raise ValueError(repr(raw_input))", "is_user_code": true,
                          "code_context": [...]},
  "chained": [],
  "raw": "Traceback (most recent call last):\n..."
}
```

**`deepest_user_frame` is what you point your first breakpoint at.** It's the deepest frame that doesn't live in site-packages or the stdlib.

### `--context-lines N`

Attach N source lines on each side of each frame's line (default 2). Drop to 0 for terse output, up to 10 if you need broader context.

### Worked example — parse a CI failure

A CI run failed. You grabbed the traceback into `ci_fail.txt`:

```powershell
dbga localize --file ci_fail.txt --context-lines 3
```

You learn: `app.py:17` in `main()`, `ValueError: bad input: ''`. Now you can:

```powershell
dbga session start --break-at app.py:17 -- app.py
dbga session eval --expr "raw_input"     # what was passed?
```

Note: `session start`'s positional is a **path to a Python script**. `-m module` / `-c code` invocations aren't supported — point at the script file directly.

## `diagnose` — Crash → Paused, One Call

```powershell
dbga diagnose --timeout 20 -- python my_app.py --flag
```

What it does:

1. Runs the command (with the supplied timeout, tree-killed if it hangs).
2. If a parseable traceback is found in the combined stdout/stderr, parses it.
3. By default (`--rerun`), spawns a session with a breakpoint at the deepest user frame and re-launches the program. You land paused there, with full auto-context.

`diagnose` strips a leading `python`/`python3`/`py` interpreter and uses the next non-flag arg as the script. It cannot rerun `python -m foo` or `python -c "..."` (no script path to hand to debugpy).

Response (rerun=true, crash):

```json
{
  "status": "diagnosed",
  "traceback": {
    "error_type": "ValueError",
    "message": "bad input: ''",
    "frames": [...],
    "deepest_user_frame": {"file": "app.py", "line": 17, "func": "main", ...}
  },
  "session_context": {
    "status": "stopped",
    "reason": "breakpoint",
    "session_id": "default",
    "location": {"file": "app.py", "line": 17, "function": "main"},
    "source": [...],
    "locals": [{"name": "raw_input", "type": "str", "value": "''"}],
    "stack": [...],
    "output": "",
    "warnings": []
  }
}
```

You can now `session eval`, `session step`, `session continue` against the live session named `default` (or whatever you passed via `--session`).

Response (no crash, command ran clean):

```json
{"status": "no_crash", "exit_code": 0, "duration_ms": 412, "timed_out": false, "stdout": "...", "stderr": ""}
```

Response (crash but `--no-rerun`):

```json
{"status": "crash", "exit_code": 1, "duration_ms": 137, "timed_out": false,
 "stdout": "...", "stderr": "...", "traceback": {...}}
```

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
dbga diagnose --timeout 10 -- python script.py --input bad.json
# → status: stopped, paused at script.py:42 in load_config(), locals: path='bad.json', data=None

# That's the symptom. The bug is upstream — load_config returned None.
dbga session continue --to script.py:30          # disposable bp at the data source
# → stopped at script.py:30, locals: text='', f=<file>

# Now we see it: the file was opened but empty. The real bug is the upstream config-build step.
dbga session release
```

`diagnose` got you to the symptom in one call. From there it's the normal workflow loop.

## Edge Cases

- **SyntaxError** — no stack. `deepest_user_frame` is the file:line of the syntax error itself. `diagnose` will still try to rerun, but the launch will fail because the file doesn't parse — surface the `localize` payload and fix the syntax first.
- **`-m` / `-c` invocation** — `diagnose` can't recover a launchable script target. The response is `{"status": "crash", "traceback": {...}, "note": "cannot rerun: 'python -m'/'python -c' invocations are unsupported"}`. Fall back to `localize` + a manual `session start` pointed at the underlying script file.
- **Tracebacks with mixed user + library frames** — the parser walks bottom-up and picks the deepest frame whose path doesn't contain `site-packages`, `/lib/python`, or `\Lib\`. If your project lives under a path that looks like a library, you may need to point breakpoints manually.
- **Chained exceptions** — the deepest user frame across *both* chains is selected. The `frames` array contains both chains with a `chain_marker` separator entry.
