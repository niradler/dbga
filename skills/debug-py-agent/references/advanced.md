# Advanced Techniques — Hangs, Concurrency, Wolf-Fence, Deep State

When the basic loop (`workflow.md`) isn't enough — the program hangs, threads race, state is nested ten layers deep, or you're hunting one bad iteration in a million.

## Hangs and Infinite Loops

A program that runs forever *is* information: something is stuck. Don't guess — interrupt and observe.

```powershell
# Already started — the session is blocking on whatever it's running
debug-cli session pause
# → returns immediately with a stop context wherever execution happened to be
#   location, locals, stack — all there
```

Read the response:

- **Same file:line on repeated pause** → you're in a tight loop (or blocked on the same call). Inspect locals to see what's not progressing.
- **Different lines, but same call stack root** → some outer function is spinning. Look at the loop variable.
- **Stuck in `select`, `recv`, `wait`, `acquire`, `read`** → blocking I/O or a lock. Check what resource you're waiting on.

### Worked example — infinite loop

```powershell
debug-cli session start -- python -m proc
# (CLI hangs on initial stop because the program runs without breakpoints — wait, then:)
debug-cli session pause
# → location: proc.py:55, locals: i=99999, target=100
# → loop is `while i < target: ...` but `i` is never incremented
debug-cli session eval --expr "i += 1; i"      # NOTE: side-effectful — only use to confirm the theory
# Confirmed root cause. Edit, restart.
```

### Worked example — deadlock

```powershell
debug-cli session pause
# → stopped at lock_a.acquire(), thread #1
# → other thread holds lock_a and is itself blocked on lock_b
```

Inspect the stack at the stop. To check whether *another* thread is the culprit, use a probe (`instrument`) to dump all thread states before the deadlock, since the basic CLI doesn't currently expose per-thread switching:

```powershell
debug-cli instrument add lock_helper.py:20 --kind log \
  --code "import faulthandler, sys; faulthandler.dump_traceback(file=sys.stderr)"
```

Run again, capture the dump from stderr, then `localize` the thread that's stuck where it shouldn't be.

## Concurrency — Race Conditions

If a value is wrong but the synchronous code path looks correct, ask: *is another thread / task mutating this between observations?*

Tells:

- Variable values change "by themselves" between `session step` and `session inspect`
- The bug only reproduces under load
- A `print`-debugging session hides the bug (timing shifts)

Strategy:

1. **Find the shared mutable state.** Look for module-level variables, instance attributes, cache dicts, lazy singletons.
2. **Instrument both writes and reads** with timestamps — see `instrumentation.md` for the probe pattern.
3. **Confirm the interleaving.** If write@T1 then read@T2 (T2<T1) gives wrong value, you've got a race. Fix with a lock, queue, or single-writer pattern.

Avoid trying to use a debugger session to *catch* a race — pausing changes timing and the race disappears. Instrumentation (which doesn't pause) is the right tool here.

## Wolf-Fence — Bisecting Loops

A loop goes wrong at an unknown iteration in 10,000. Don't single-step. Binary-search:

```powershell
debug-cli session start --break-at "app.py:45:i == 5000" -- python -m proc
# → stopped at i=5000
debug-cli session eval --expr "is_valid(state)"
# → True  → bug is after iteration 5000

debug-cli session set-bp "app.py:45:i == 7500"
debug-cli session clear-bp app.py:45         # the i==5000 one
debug-cli session continue
# → stopped at i=7500
debug-cli session eval --expr "is_valid(state)"
# → False → bug is between 5000 and 7500. Halve again.
```

~14 iterations to find the bad step out of 10,000. Not 10,000 step commands.

### Variant — wolf-fence across files

If you don't know which *file* the corruption happens in, set breakpoints at module boundaries:

```powershell
debug-cli session set-bp parser.py:exit
debug-cli session set-bp validator.py:entry
# (use actual line numbers for the exit/entry points)
debug-cli session continue
# → which one stops first? where's the state still good vs already bad?
```

Boundary breakpoints are cheap and highly informative.

## Deep Nested State

Auto-context truncates collections to a 5-item preview and strings to 200 chars. When you need to see deeper, use `variables_reference` (the DAP handle returned in `locals`) — currently exposed via:

```powershell
debug-cli session eval --expr "data['nested']['list'][3]['payload']"
debug-cli session eval --expr "json.dumps(data, default=str, indent=2)[:2000]"
```

The second pattern (serialize to JSON, slice) is robust for objects whose `__repr__` is unhelpful. Don't try to dump 50MB into the response — slice or scope first.

For pandas / numpy:

```powershell
debug-cli session eval --expr "df.head(20).to_dict('records')"
debug-cli session eval --expr "arr.shape, arr.dtype, arr.ravel()[:50].tolist()"
```

## Crashes Inside C Extensions / Native Code

debugpy can't step into C extensions (numpy internals, lxml, custom .so). When the failure is inside one:

- **Pre-call inspection** — break *just before* the C call, log every argument exhaustively
- **Post-call inspection** — break *just after*, capture all outputs
- **Hypothesis: argument type mismatch** is the most common cause. Check `type(arg)`, `arg.dtype`, `arg.shape` for every numpy-style input
- If you genuinely need a native stack trace, run under `gdb python` or `lldb python` outside `debug-cli` — that's beyond Python-level debugging

## Subprocess Crashes

A child process crashes and you can't attach a session to it from the parent. Options:

1. **Run the child under `debug-cli diagnose`** directly, reproducing its invocation outside the parent.
2. **Capture the child's stderr** in the parent and `localize` the traceback.
3. **Instrument the child's entry point** to set up a `breakpoint()` that fires only under a specific env var:
   ```powershell
   debug-cli instrument add child.py:1 --kind breakpoint \
     --code "import os; os.environ.get('DEBUG_CHILD') and breakpoint()"
   ```
   Then run with `DEBUG_CHILD=1` set. The child halts; you can attach `pdb` over stdin or pivot to `--listen`.

## Flaky Tests

A test passes 9/10 runs and fails the 10th. Don't add prints — they shift timing.

Strategy:

1. **Find the assertion** that flaked. Localize from the failure output.
2. **Instrument with a conditional probe** that dumps state on the failing path:
   ```powershell
   debug-cli instrument add test_foo.py:42 --kind log \
     --code "if not (a == b): print(f'FLAKE a={a!r} b={b!r}', flush=True)"
   ```
3. **Run the test in a tight loop** with `run --timeout` per iteration. Capture the dump.
4. Analyze the dump — usually reveals an uninitialized variable, a stale cache, or a missing await.

## Memory / Resource Leaks

Outside the scope of this skill — use `tracemalloc`, `objgraph`, or `memray` directly. `debug-cli session` can pause for inspection but doesn't summarize allocation patterns.

## When You're Genuinely Stuck

Two strikes, rethink. Then:

1. **Re-read the code with fresh eyes** — assume your prior theory is wrong, start from `main()`.
2. **Explain the bug out loud** (rubber duck) — the gap in your explanation is where the bug is.
3. **Bisect commits** (`git bisect`) — when did the bug appear? What changed?
4. **Set up `superpowers:systematic-debugging`** — if you haven't worked through its 4 phases, do that before more probing.

If you've spent 30 minutes without a new piece of evidence, you're stuck. Stop debugging, step back, find a fresh angle.
