# Debugging Node/TS with `dbga` (vscode-js-debug)

Node-specific recipes for the evidence-first loop. The full discipline lives in the `debug-agent` skill and `_shared/evidence-first.md` — reference them by name; this file is the Node delta only.

## Prerequisites

```powershell
dbga --version            # expect 0.1.1+
node --version            # current LTS
```

Node debugging runs over **vscode-js-debug**. It is not on npm. Discovery order:

1. `$DBGA_JS_DEBUG_SERVER` (point it at the extracted `dapDebugServer.js` / server dir).
2. VS Code / Cursor / Insiders extension dirs (auto-detected).
3. Manual extract of `js-debug-dap-vX.Y.Z.tar.gz` from the [vscode-js-debug releases](https://github.com/microsoft/vscode-js-debug/releases) into `~/.local/share/js-debug` (POSIX) or `%LOCALAPPDATA%\js-debug` (Windows).

If `session start --lang node` fails to find the adapter, set `$DBGA_JS_DEBUG_SERVER` and retry.

## Auto-detection

`.js .mjs .cjs .ts .mts .cts` auto-detect to `--lang node`; you can still pass `--lang node` explicitly. `--cwd <dir>` is recommended so the adapter resolves modules from the project root.

## Crash → triage in one call

```powershell
dbga diagnose --timeout 60 --cwd <dir> -- node buggy.js
```

Returns `"status": "diagnosed"` with `error_type`, `message`, and the `deepest_user_frame`. Example: `error_type: "TypeError"`, `message: "Cannot read properties of null (reading 'value')"`, deepest user frame `main` line 10. `node:internal/*` frames are marked `is_user_code: false`, so the deepest *user* frame is what you get.

`diagnose` reuses session `default`; clear a lingering one with `dbga session release` first.

## Live inspection

```powershell
dbga session start --session node-demo --cwd <dir> --break-at buggy.js:3 --pretty -- buggy.js
dbga session eval --session node-demo --expr "nums"     # → (3) [10, 20, 30]  (JS formatting)
dbga session continue --session node-demo
dbga session release --session node-demo
```

Pause at program start instead of a breakpoint:

```powershell
dbga session start --session n --stop-on-entry --pretty -- buggy.js   # reason: entry
```

`eval` runs in the **target language** — vscode-js-debug evaluates the expression as JavaScript and formats values with JS syntax (`(3) [10, 20, 30]`, not Python's `[10, 20, 30]`).

## TypeScript notes

- `session start` takes a **script path**, not a shell command (no `ts-node -e`). Run a transpiled `.js`, or a `.ts` entry under a runtime/loader that the adapter launches.
- Breakpoints map through source maps. If a breakpoint doesn't bind, confirm `sourceMap: true` in `tsconfig` and that the emitted `.js.map` sits next to the `.js`.
- A `--break-at file:line` referencing the `.ts` source resolves via the source map; if it won't bind, set it on the emitted `.js` line instead.

## Honest limit — single process

Only a **single launched process** is validated. `worker_threads`, `child_process`, and `cluster` multi-process lifecycles are not yet validated. For multi-process bugs, isolate the failing worker into a standalone script and debug that.

## When to reach for this

Wrong output, a `TypeError`/`undefined` access, a hang, or any value that "shouldn't be possible" — set a breakpoint where the value *first* goes wrong (walk up the stack), eval to confirm, then verify the fix at that same breakpoint. Don't print-debug; one stop returns full context.
