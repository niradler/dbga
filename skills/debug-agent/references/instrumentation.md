# Instrumentation — Reversible Source Probes

`dbga instrument` inserts a probe (a `print`, a `breakpoint()`, a trace logger, or arbitrary code) directly into the source file at a given `file:line`. The original file is snapshotted on first touch, so a single `instrument revert --all` rolls every probe back atomically. The probe is inserted **before** the target line at the indentation of that target line.

This is the right tool when a session won't help:

- **Long-running jobs** — pausing every iteration is too expensive
- **Non-stop debugging** — you need the program to keep running and just *record* what passes through
- **Production-like reproductions** — running under a debugger changes timing; a print doesn't
- **Crossing a process boundary** — child processes don't share your DAP session
- **Sharing with a teammate** — a checked-in `instrument` change is more portable than a session transcript

It's the *wrong* tool when:

- You can pause cheaply → use `session` (richer data, no source edits)
- You need to expand nested state → `session eval`, not a print
- You're hunting a rare condition once → a conditional breakpoint is faster than rebuilding from logs

## Commands

```powershell
dbga instrument add app.py:42 --kind log        --code "print('items=', items, flush=True)"
dbga instrument add app.py:42 --kind breakpoint --code "breakpoint()"
dbga instrument add app.py:42 --kind trace      --code "trace.add('hit:42')"
dbga instrument add app.py:42 --kind custom     --code "if x is None: raise RuntimeError('bug here')"

dbga instrument list
dbga instrument revert --all                    # remove every probe, restore originals
dbga instrument revert <inst_id>                # remove a single probe by its id (positional)
```

A probe is inserted **before** the target line, at the indentation of that target line. To remove all probes from a single file, run `instrument revert <id>` for each entry that `instrument list` reports for that file, or just `instrument revert --all` if no other files are instrumented.

### `--kind` choices

| Kind | Intent | Example use |
|---|---|---|
| `log` | print observed state, keep running | `print('user_id=', user_id)` in a hot path |
| `breakpoint` | drop into pdb/debugpy when triggered | `breakpoint()` at a suspected branch |
| `trace` | structured trace event (depends on your trace lib) | wire into existing telemetry |
| `custom` | anything else — assertions, raises, side-channel writes | invariant checks |

The kind is metadata for `instrument list` and your own filtering; it doesn't change the insertion logic.

## State

All instrumentation is tracked in `.debug-agent/instrumentation.json` with original-file snapshots stored alongside. The id (`secrets.token_hex(4)`) lets `revert <id>` target one probe. Snapshots are file-level — `revert` restores the entire file to its pre-instrumentation state, so don't hand-edit a file *while* it has probes in it (or your edits will be lost on revert).

## Worked Example — Catch a Rare Wrong-Output Bug

A nightly batch job processes 50k records and occasionally writes a row with `total < 0`. You can't reproduce locally; running the whole job under a debugger would take days.

```powershell
# 1. Snapshot a probe right before the write
dbga instrument add batch.py:218 --kind log \
  --code "if total < 0: print(f'BAD total={total} row={row!r}', flush=True)"

# 2. Run the job as normal
dbga run --timeout 7200 -- python batch.py --date 2026-05-28

# 3. Grep the output for the BAD lines (or use watch)
dbga watch --file batch_run.log --pattern "^BAD total=" --context-lines 2

# 4. With a concrete row in hand, set up a targeted session
dbga session start --break-at "batch.py:200:row['id'] == 'abc-123'" -- batch.py --date 2026-05-28

# 5. When done, undo every probe in one shot
dbga instrument revert --all
```

Key idea: instrumentation finds *which* record fails; the session figures out *why*. Don't try to do both with the same tool.

## Worked Example — Crash That Requires Async Context

A `aiohttp` handler crashes once per ~1000 requests with no useful traceback (the framework swallows it). A breakpoint hangs the event loop and prevents reproduction.

```powershell
# Drop an exception-catching probe right where it crashes
dbga instrument add handlers/users.py:88 --kind custom --code "import traceback; traceback.print_exc(); raise"

# Run the server under your normal load test
dbga run --timeout 600 -- python server.py

# Capture the traceback from stderr, localize, then revert
dbga localize --file stderr.txt
dbga instrument revert --all
```

## Safety Rules

- **Don't commit probe-modified source.** `instrument` writes into the real file. If you forget to revert before `git add -A`, you'll commit `print(...)` lines into a repo. Workflow: `instrument add → reproduce → instrument revert --all → git diff` (should be clean).
- **Targets outside `--cwd` need `--allow-outside`.** By default, probes refuse to touch files outside the working directory to prevent accidental edits to site-packages.
- **Indentation is auto-matched, not auto-validated.** If you insert into a block where the parser can't find a sane indent level (top-of-file, blank file), you'll get an explicit error. If your probe is syntactically broken, Python will fail at import — `instrument revert --all` is your escape hatch.
- **One probe per (file, line).** Re-running `instrument add` at the same location replaces the prior probe at that exact line; if you need multiple probes around one line, put them at adjacent lines.

## Inspecting State

```powershell
dbga instrument list
```

Response:

```json
{
  "instrumentations": [
    {"id": "a3f1b2c0", "file": "app.py", "line": 42, "kind": "log",        "code": "print('x=', x)"},
    {"id": "9d8e7c6b", "file": "app.py", "line": 88, "kind": "breakpoint", "code": "breakpoint()"}
  ]
}
```

The `id` is what `revert <id>` takes (positional). Tokens are short and human-typable.
