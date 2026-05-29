---
name: node
description: >-
  Use when writing, reviewing, or fixing Node.js or TypeScript code — type errors (TS2322, TS2345, "is not assignable"), `tsconfig`/strict-mode issues, async/await bugs, unhandled promise rejections, `Cannot read properties of undefined`, EventEmitter/stream/worker code, npm/pnpm/Express/Fastify backends, Jest/Vitest tests, or plain-JS (no types) work. Keywords: typescript, ts, node, esm, async, promise, generics, vitest, jest.
---

# Node.js / TypeScript

TypeScript-first development skill. Delivers strict-typed, clean, verified Node/TS code. JavaScript without types is the fallback, not the default.

## Core stance

- **Strict TypeScript.** `strict: true` with every flag on; no `any` without a justification; types model the domain, not the other way around.
- **Type inference over annotation.** Annotate public API boundaries and let inference carry the rest.
- **Evidence first.** When code crashes, hangs, or returns wrong output, gather runtime evidence with `dbga` and the `debug-agent` skill before guessing. See `references/debugging.md`.
- **Clean, self-explaining code; no comments unless asked** — see `_shared/clean-code.md` (cross-reference, do not restate).
- **Audit then suggest dependency bumps** (`npm outdated`, `npm audit`) — see `_shared/dependency-hygiene.md`.
- **Validation discipline** — see `_shared/evidence-first.md`.

## References — load on demand

| Need | Read |
| --- | --- |
| Module/composition/DI patterns, anti-patterns | `references/design-patterns.md` |
| Advanced types: conditional, mapped, template-literal, branded, discriminated unions, `infer`, utility types | `references/typescript-types.md` |
| async/await, Promise combinators, concurrency limits, streams, EventEmitter, graceful shutdown | `references/async-patterns.md` |
| Typed errors, Result types, `never` exhaustiveness, custom error classes, async error wrapping | `references/errors-structure.md` |
| Plain JS with no types: JSDoc typing, defensive coding, ESM | `references/js-fallback.md` |
| `dbga` + vscode-js-debug recipes for Node/TS | `references/debugging.md` |

## Toolchain

- Runtime: `node` (use a current LTS). Package manager: npm / pnpm.
- Type-check: `tsc --noEmit`. Lint/format: ESLint + Prettier.
- Test: Vitest (preferred) or Jest. Cover edge cases, not just the happy path.
- Run a real flow (`tsc --noEmit`, the test suite, or the actual command) before declaring anything done.

## Evidence-First Debugging (debug-agent toolkit)

You have `dbga` — an evidence-first debugger for Python/Go/Node over DAP — and the `debug-agent` skill. When code crashes, hangs, produces wrong output, or you need live runtime state, DO NOT guess from source. Gather evidence:

- `dbga diagnose --timeout 60 --cwd <dir> -- node buggy.js` → triage a crash to the deepest user frame
- `dbga session start --break-at file:line -- <script>` then `dbga session eval --expr "<x>"` → inspect live state
- Invoke the `debug-agent` skill for the full evidence-first loop.

Node uses vscode-js-debug (set `$DBGA_JS_DEBUG_SERVER` if not auto-discovered); only a single launched process is validated today. Validate against real use flows and verify the fix at the original fault before declaring it done.
