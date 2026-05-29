---
name: python
description: Use when writing, reviewing, refactoring, or debugging Python — modules, packages, CLIs, async/asyncio code, FastAPI/Django/Flask services, data pipelines, or scripts. Triggers on Python keywords (def, class, async/await, asyncio, dataclass, Protocol, type hints, mypy, ruff, uv, pytest, pydantic), Python errors (TypeError, ValueError, ImportError, AttributeError, tracebacks), and tasks like "write/fix/optimize Python", "add type hints", "make this async", "Pythonic", ".py file".
---

# Python

Idiomatic, type-safe, production Python (3.10+, modern toolchain: uv, ruff, mypy --strict, pytest). This file is a slim index — load the reference for the task at hand.

## Cross-cutting discipline (do not restate — follow by name)

- **Clean, self-explaining code** → `_shared/clean-code.md`. No comments unless asked; clear names over cleverness; guard clauses over nesting.
- **Evidence-first development & debugging** → `_shared/evidence-first.md` + the `debug-agent` skill. Validate against real runs; verify at the original fault.
- **Dependency hygiene** → `_shared/dependency-hygiene.md`. Audit (`pip-audit`, `uv pip list --outdated`); suggest bumps, don't run them.

## Route to a reference

| Task / symptom | Reference |
| --- | --- |
| Structure code, layering, DI, SRP, composition, anti-patterns | `references/design-patterns.md` |
| Type hints, generics, Protocols, TypeVar, mypy strict, TypedDict | `references/type-hints.md` |
| async/await, asyncio, tasks, queues, semaphores, blocking-in-async | `references/async-concurrency.md` |
| Custom exceptions, chaining, partial-failure batches, validation | `references/errors-structure.md` |
| Crash, hang, wrong value, live state — debug a `.py` with `dbga` | `references/debugging.md` |

## Defaults

- **Python 3.10+**. Use `X | None`, `list[str]`, `match`, `dataclass`/`pydantic`, `Protocol` for structural typing.
- **Type everything public.** Full annotations on signatures and attributes; `mypy --strict` clean. See `references/type-hints.md`.
- **Async-first for I/O.** Never block the event loop; offload sync work with `asyncio.to_thread`. See `references/async-concurrency.md`.
- **Toolchain:** `uv` (deps/venv), `ruff` (lint+format), `mypy --strict`, `pytest`. Prefer the stdlib before adding a dependency.
- **Errors carry context** and chain with `raise ... from e`; validate at boundaries. See `references/errors-structure.md`.

## Evidence-First Debugging (debug-agent toolkit)

You have `dbga` — an evidence-first debugger for Python/Go/Node over DAP — and the `debug-agent` skill. When code crashes, hangs, produces wrong output, or you need live runtime state, DO NOT guess from source. Gather evidence:

- `dbga diagnose -- <cmd>`  → triage a crash to the deepest user frame
- `dbga session start --break-at file:line -- <script>` then `dbga session eval --expr "<x>"` → inspect live state
- Invoke the `debug-agent` skill for the full evidence-first loop.

Validate against real use flows and verify the fix at the original fault before declaring it done. Python recipes: `references/debugging.md`.

## Delegation

For deep Python work, the `python-expert` agent drives this skill plus `debug-agent`. The `architect` agent orchestrates cross-language work.
