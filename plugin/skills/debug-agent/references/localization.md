# Localization — `localize` and `diagnose`

When the program already crashed, your first job is to point at a *specific file and line* — the deepest user frame, where your code (not the framework, not site-packages, not the runtime) sits on top of the traceback. Two commands cover this:

- **`localize`** — parses a traceback into structured frames. No execution. Pure function.
- **`diagnose`** — runs the command, parses the traceback, reruns under a session paused at the deepest user frame. One call from "crash" to "paused at the bug."

Use `diagnose` for crashes you can re-trigger. Use `localize` when you only have the traceback text (CI log, error report, screenshot OCR).

## Languages and `--lang`

Both commands take `--lang {python,go,node}`. When omitted, the language is auto-detected from the script's file extension: `.py`→python, `.go`→go, `.js`/`.mjs`/`.cjs`/`.ts`/`.mts`/`.cts`→node. In practice `diagnose -- go run buggy.go` and `diagnose -- node buggy.js` are detected without passing `--lang` at all.

Each language has its own traceback grammar, but the structured output (`error_type`, `message`, `frames`, `deepest_user_frame`) is identical:

- **Python** — standard tracebacks. `ZeroDivisionError`-style crashes resolve to the deepest non-library frame (`site-packages`/stdlib are skipped).
- **Go** — `panic:` / `fatal error:` dumps. Runtime scaffolding frames are marked non-user so `deepest_user_frame` lands on your code (e.g. `main.average`); file paths come back forward-slash even on Windows.
- **Node/TS** — V8 stack traces. `node:internal/...` frames are classified `is_user_code: false`, so the deepest *user* frame is the one in your own file.

## `localize` — Parse a Traceback

Read a traceback from a file:

```powershell
dbga localize --lang python --file traceback.txt
```

It handles:

- Standard tracebacks
- Chained exceptions (`During handling of the above exception, another exception occurred:` / `The above exception was the direct cause of the following exception:`)
- `SyntaxError` (no stack — just file:line + caret)
- pytest short-form output

The response carries `error_type`, `message`, a `frames` array (each with `file`, `line`, `func`, `code`, `is_user_code`, `code_context`), the picked `deepest_user_frame`, any `chained` exceptions, and the `raw` text. For example, parsing the `buggy.py` crash yields `error_type: "ZeroDivisionError"`, `message: "division by zero"`, and a `deepest_user_frame` of `average` at line 3.

**`deepest_user_frame` is what you point your first breakpoint at.** It's the deepest frame that doesn't live in site-packages or the stdlib.

### `--context-lines N`

Attach N source lines on each side of each frame's line (default 2). Drop to 0 for terse output, up to 10 if you need broader context.

### Worked example — parse a saved traceback

You saved a Python traceback (CI log, error report) into `py_trace.txt`:

```powershell
dbga localize --lang python --file py_trace.txt
```

For the `buggy.py` crash you learn: `buggy.py:3` in `average()`, `ZeroDivisionError: division by zero`. Now you can:

```powershell
dbga session start --break-at buggy.py:3 -- buggy.py
dbga session eval --expr "nums"     # what was passed?
```

Note: `session start`'s positional is a **path to a script** (Python `.py`, Go `.go`, or Node `.js`/`.ts`). `-m module` / `-c code` invocations aren't supported — point at the script file directly.

### Worked example — a Go panic

You captured a panic dump from a Go service into `go_trace.txt`:

```powershell
dbga localize --lang go --file go_trace.txt
# error_type: "panic", message: "runtime error: integer divide by zero"
# deepest_user_frame: {"file": "buggy.go", "line": 10, "func": "main.average"}
```

Runtime scaffolding frames are skipped automatically — `deepest_user_frame` points at `main.average`, your code. (File paths come back forward-slash even on Windows.)

### Worked example — a Node V8 stack

```powershell
dbga localize --lang node --file node_trace.txt
# error_type: "TypeError", message: "Cannot read properties of null (reading 'value')"
# deepest_user_frame: {"file": "buggy.js", "line": 10, "func": "main"}
```

`node:internal/...` frames are flagged as library code (`is_user_code: false`), so the deepest *user* frame is `main` in `buggy.js`.

## `diagnose` — Crash → Paused, One Call

```powershell
dbga diagnose --timeout 20 -- python my_app.py --flag
dbga diagnose --timeout 20 -- go run main.go --flag      # auto-detected as Go
dbga diagnose --timeout 20 -- node app.js                # auto-detected as Node
```

What it does:

1. Runs the command (with the supplied timeout, tree-killed if it hangs).
2. If a parseable traceback is found in the combined stdout/stderr, parses it.
3. By default (`--rerun`), spawns a session with a breakpoint at the deepest user frame and re-launches the program. You land paused there, with full auto-context.

`diagnose` peels the interpreter off the front of the command and uses the next non-flag arg as the launch target:

- **Python** — strips `python`/`python3`/`py`; cannot rerun `python -m foo` or `python -c "..."` (no script path to hand to debugpy).
- **Go** — peels `go run <main.go> args...` (`go run` flags are skipped). `go test` is out of scope — there's no `mode:"test"` rerun, so `diagnose -- go test ...` returns the parsed traceback only.
- **Node** — peels `node [-flags] script.js args` and `ts-node`/`tsx` invocations, including the `-r module` / `--require module` pair. Go needs `dlv` on PATH; Node needs `node` + vscode-js-debug (see `debugger.md`).

Response (rerun=true, crash) — values shown are from the live `buggy.py` run:

```json
{
  "status": "diagnosed",
  "traceback": {
    "error_type": "ZeroDivisionError",
    "message": "division by zero",
    "frames": [...],
    "deepest_user_frame": {"file": "buggy.py", "line": 3, "func": "average", ...}
  },
  "session_context": {
    "status": "stopped",
    "reason": "breakpoint",
    "session_id": "default",
    "location": {"file": "buggy.py", "line": 3, "function": "average"},
    "source": [...],
    "locals": [{"name": "total", "value": "60"}],
    "stack": [...],
    "output": "",
    "warnings": []
  }
}
```

The rerun session here paused at `average:3` with a 3-frame stack (`average` → `main` → `<module>`). You can now `session eval`, `session step`, `session continue` against the live session named `default` (or whatever you passed via `--session`).

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
dbga diagnose --timeout 30 --pretty -- python buggy.py
# → status: diagnosed; error_type "ZeroDivisionError", "division by zero"
# → reran into a session paused at buggy.py:3 in average(), locals include total=60

# Paused at the symptom. Inspect why the divisor was zero:
dbga session eval --session default --expr "nums"
# → "[]"  ← average() was called with an empty list

dbga session release --session default
```

`diagnose` got you to the symptom in one call. From there it's the normal workflow loop.

### Worked example — Go and Node

```powershell
# Go: dlv compiles + runs buggy.go, pauses at the panic site
dbga diagnose --timeout 60 --cwd <dir> --pretty -- go run buggy.go
# → status: diagnosed; error_type "panic", "runtime error: integer divide by zero"
# → deepest_user_frame: main.average at buggy.go:10; reran into a session paused there

# Node: vscode-js-debug launches buggy.js, pauses at the throw site
dbga diagnose --timeout 60 --cwd <dir> -- node buggy.js
# → status: diagnosed; error_type "TypeError", "Cannot read properties of null (reading 'value')"
# → deepest_user_frame: main at buggy.js:10; reran into a session paused there
```

`diagnose` auto-detects the language from the command (no `--lang` needed). The `session_context` shape and `eval`/`step`/`continue` ops are identical to Python — only the language of `eval` expressions differs (Go expr / JS expr). See `debugger.md`.

> **Rough edge:** `diagnose` reuses the session name `default`. A lingering `default` session (from an earlier `diagnose` you never released) makes the next call return `{"status":"error","error_type":"session_exists",...}`. Clear it with `dbga session release` first.

## Edge Cases

- **SyntaxError** — no stack. `deepest_user_frame` is the file:line of the syntax error itself. `diagnose` will still try to rerun, but the launch will fail because the file doesn't parse — surface the `localize` payload and fix the syntax first.
- **`-m` / `-c` invocation** — `diagnose` can't recover a launchable script target. The response is `{"status": "crash", "traceback": {...}, "note": "cannot rerun: 'python -m'/'python -c' invocations are unsupported"}`. Fall back to `localize` + a manual `session start` pointed at the underlying script file.
- **Tracebacks with mixed user + library frames** — the parser picks the deepest frame that isn't library code. Library detection is per-language: Python skips `site-packages`/stdlib paths, Go skips `runtime.`/`sync.`/`reflect.`/`internal/` frames, Node skips `node:internal/...` and `node_modules`. If your project lives under a path that looks like a library, you may need to point breakpoints manually.
- **`go test` / non-launchable Go targets** — `diagnose` returns the parsed traceback without a rerun (no `mode:"test"` support yet). Use `localize` + a manual `session start` against a `.go` file or package.
- **Chained exceptions** — the deepest user frame across *both* chains is selected. The `frames` array contains both chains with a `chain_marker` separator entry.
