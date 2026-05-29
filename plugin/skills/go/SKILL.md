---
name: go
description: >-
  Use when writing, reviewing, or fixing Go code — goroutines, channels, select, sync, context, errgroup; data races, deadlocks, goroutine leaks; error wrapping with %w, errors.Is/As, sentinel and typed errors; interfaces, generics, functional options; go.mod, go test -race, go vet, golangci-lint, govulncheck, dlv. Symptoms: "race detected", "all goroutines are asleep - deadlock", panic, leaking goroutines, nil-pointer deref.
---

# Go development

Idiomatic, concurrent, evidence-verified Go (1.21+). This SKILL.md is a slim
index — load the reference for the task at hand.

## Core principles (Go deltas on the shared rules)

- **Accept interfaces, return structs.** Small, focused interfaces defined at
  the consumer.
- **Don't communicate by sharing memory; share memory by communicating.**
  Channels for orchestration, mutexes for state.
- **Errors are values.** Handle explicitly; wrap with context. `panic` only for
  programmer errors.
- **Composition over inheritance** via embedding. Functional options for config.
- Language-invariant rules live in the shared references — read them by name,
  don't expect them restated here:
  - `_shared/clean-code.md` — self-explaining code; Go exception: exported-
    identifier doc comments are idiomatic, keep those; add no other comments.
  - `_shared/evidence-first.md` — observe before you fix.
  - `_shared/dependency-hygiene.md` — Go specifics below.

## References — load on demand

| Task | Read |
| --- | --- |
| Interfaces, generics, options, package layout, idioms/anti-patterns | `references/design-patterns.md` |
| Goroutines, channels, select, sync, context, worker pools, errgroup | `references/concurrency.md` |
| Error wrapping, `errors.Is/As`, sentinel/typed errors, panic boundaries | `references/errors-structure.md` |
| Debug a crash/race/deadlock/hang with `dbga` + `dlv` | `references/debugging.md` |

## Dependency hygiene (Go)

On setup or when touching deps, audit then suggest bumps:

```sh
go list -u -m all      # what's outdated
go get -u ./...        # update
go mod tidy
govulncheck ./...      # known vulnerabilities
```

See `_shared/dependency-hygiene.md` for the audit-then-suggest discipline.

## Quality gate (run before declaring done)

```sh
gofmt -l .             # must print nothing
go vet ./...
golangci-lint run
go test -race ./...    # race detector on
```

## Evidence-First Debugging (debug-agent toolkit)

You have `dbga` — an evidence-first debugger for Python/Go/Node over DAP — and
the `debug-agent` skill. When code crashes, hangs, produces wrong output, or you
need live runtime state, DO NOT guess from source. Gather evidence:

- `dbga diagnose --lang go --cwd <module dir> -- go run <main>` → triage a crash
  to the deepest user frame
- `dbga session start --lang go --cwd <module dir> --break-at file.go:line -- <main>`
  then `dbga session eval --expr "<x>"` → inspect live state
- Invoke the `debug-agent` skill for the full evidence-first loop.

Concurrency bugs first: `go test -race ./...`. Validate against real use flows
and verify the fix at the original fault before declaring it done. Details and
`dlv` recipes in `references/debugging.md`.
