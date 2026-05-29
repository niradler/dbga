# Debugging Go — evidence first

Observe what *does* happen; don't infer from source. The discipline is in
`_shared/evidence-first.md` and the full loop is the `debug-agent` skill. This
file is the Go-specific recipe sheet.

Prereq: Delve on PATH — `go install github.com/go-delve/delve/cmd/dlv@latest`.
Always pass `--lang go` and `--cwd <module dir>` (the dir holding `go.mod`).
`dbga` returns file paths with forward slashes even on Windows.

## First move by symptom

| Symptom | First move |
| --- | --- |
| Panic / crash with a stack | `dbga diagnose` (triage to deepest user frame) |
| Have only the panic text | `dbga localize --lang go --file trace.txt` |
| Wrong value, need live state | `dbga session start --break-at` + `eval` |
| `race detected` | `go test -race ./...` then session at the racy access |
| `all goroutines are asleep - deadlock` / hang | goroutine dump (below) + `dlv goroutines` |

## Crash → triage in one call

`diagnose` reruns the program paused at the deepest user frame with full
context (location, source, locals, stack, recent output).

```sh
dbga diagnose --lang go --timeout 60 --cwd ./cmd/app --pretty -- go run .
```

Returns `"status": "diagnosed"` with `error_type` (e.g. `panic`), `message`
(e.g. `runtime error: integer divide by zero`), and `deepest_user_frame`
(e.g. `main.average` line 10). `diagnose` reuses session `default`; if one is
alive you get `session_exists` — clear it with `dbga session release` first.

## Live session — inspect and verify

```sh
dbga session start --lang go --session go-bug --cwd ./cmd/app \
  --break-at calc.go:10 --pretty -- go run .

dbga session eval --session go-bug --expr "nums"   # → []int len: 3, cap: 3, [10,20,30]
dbga session eval --session go-bug --expr "total"
dbga session continue --session go-bug             # re-hits the breakpoint
dbga session release  --session go-bug             # always clean up
```

`eval` runs in Go via Delve, with Go value formatting. Set the breakpoint where
the value *first* goes wrong, not where it blows up — walk up the stack to the
origin. Verify a fix by evaluating the fix-expression against live state at the
same breakpoint before editing.

## Concurrency: races, deadlocks, leaks

Run the race detector first — it pinpoints the conflicting accesses:

```sh
go test -race ./...
go run -race .
```

For a hang/deadlock, dump every goroutine's stack by sending `SIGQUIT`
(`Ctrl+\` on POSIX), or set `GOTRACEBACK=all`. The dump shows which goroutines
are blocked on which channel/lock — the cycle is your deadlock; a goroutine
stuck forever with no exit path is your leak (cross-check `concurrency.md`).

Then drive a live session: break just before the suspect channel op or
`Lock()`, `eval` the relevant state, and step. For goroutine-level inspection
beyond `dbga`, attach `dlv` directly (below).

## Raw dlv when you need goroutine/thread control

`dbga` covers the evidence-first loop; drop to `dlv` for goroutine switching,
deferred-call inspection, or core dumps.

```sh
dlv debug ./cmd/app -- <args>     # build + debug
dlv test ./pkg/...                # debug a test
dlv attach <pid>                  # attach to a running process
dlv core ./bin/app core.1234      # post-mortem from a core dump
```

Inside dlv: `break pkg.Func`, `continue`, `goroutines`, `goroutine <id>`,
`stack`, `print <expr>`, `locals`, `next`, `step`.

## Profiling (when "slow", not "wrong")

```sh
go test -bench=. -benchmem -cpuprofile cpu.out -memprofile mem.out ./...
go tool pprof cpu.out      # top, list <func>, web
go tool trace trace.out
```

Benchmark before optimizing; confirm the win with a second benchmark.

## Verify the fix

Re-run the real flow (`go run` / the failing `go test -race`) and confirm
correct behavior at the original fault location — not just that the program no
longer crashes. Then run the quality gate from `go/SKILL.md`.
