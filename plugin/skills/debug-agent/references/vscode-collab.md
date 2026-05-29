# VS Code Collab — `--listen`, Shared Breakpoints, Attach

Sometimes you're not debugging solo — you're pairing with a human who wants to drive from VS Code, or you want a richer UI than JSON-over-CLI. `dbga` supports two collab patterns:

1. **Shared breakpoints file** — both CLI and VS Code consume `.debug-agent/breakpoints.json`
2. **Listen mode** (`--listen PORT`) — `dbga` spawns the debuggee with debugpy listening; VS Code attaches

You can combine them: spawn with shared bps + listen, then attach from VS Code with the bps already set.

## Shared Breakpoints File

When you pass `--use-bps-file` on `session start`, the daemon merges `.debug-agent/breakpoints.json` into the initial breakpoint set. Any `set-bp` / `clear-bp` during the session is written back to the same file (unless you pass `--no-write-bps-file`).

```json
// .debug-agent/breakpoints.json
{
  "breakpoints": [
    {"file": "app.py", "line": 42},
    {"file": "worker.py", "line": 55, "condition": "i == 100"}
  ],
  "updated_at": "2026-05-28T14:00:00Z"
}
```

VS Code Python debugging stores breakpoints in `.vscode/launch.json` configuration or in its workspace state — *not* this file by default. To share, either:

- Have one teammate maintain `.debug-agent/breakpoints.json` and have the other sync VS Code breakpoints to match, or
- Use a small VS Code extension / script that mirrors VS Code's breakpoint state into the JSON file on save

The file format is intentionally simple so anyone can edit it by hand: `file`, `line`, optional `condition`.

### Worked example — handoff

You've been debugging from CLI, found the suspect region, and want to hand off to a human teammate who prefers VS Code:

```powershell
# CLI side — your session naturally wrote the bps to the shared file
dbga session list-bp
# → confirm what's there
dbga session release
```

Teammate opens VS Code:

1. Reads `.debug-agent/breakpoints.json` (or runs a sync script that copies entries into VS Code's bp list).
2. Hits F5 with their normal launch config.

They now start at the same breakpoints you were using. No "what line was it again?" round-trip.

## Listen Mode — Attach from VS Code

```powershell
dbga session start --listen 5678 --use-bps-file -- script.py        # python (auto)
dbga session start --listen 5678 --lang go   -- main.go             # go
dbga session start --listen 5678 --lang node -- app.js              # node
```

The CLI launches the debuggee under the language's listen-mode adapter and returns; the response carries the host/port and PID you then point VS Code at.

Each language requires its own adapter for `--listen`:

| Language | Listen-mode adapter | Prerequisite for `--listen` |
| --- | --- | --- |
| Python | `debugpy --listen` | bundled `debugpy` |
| Go | `dlv dap --listen` | `dlv` on PATH |
| Node/TS | vscode-js-debug DAP server | `node` + vscode-js-debug |

> **Not yet captured live.** The `--listen` attach flow has not been exercised end-to-end in the live evidence corpus. The prerequisites above are accurate (Go needs `dlv`, Node needs vscode-js-debug), but for the exact response payload, the per-language `attach_url` scheme, and the VS Code `launch.json` attach config, consult your installation rather than relying on a hard-coded example here. Treat what follows as the general shape of the workflow, not a verified transcript.

In VS Code, add an **attach** configuration to `.vscode/launch.json` for the matching debug type (`debugpy` for Python, `go` for Go, `node` for Node) pointed at `127.0.0.1` and the port you passed to `--listen`, then hit F5 to attach.

### Important constraints in listen mode

- **No daemon, no control socket.** Listen-mode skips the per-session daemon entirely — the CLI directly spawns the debuggee under `debugpy --listen` and returns. `session eval`, `session step`, `session continue`, `sessions ls`, `session release` cannot see or drive a listen-mode debuggee. Control belongs to VS Code; lifecycle is yours (`taskkill /PID 12345` on Windows, `kill 12345` on POSIX) until this gap is closed in a future release.
- **127.0.0.1 only.** The listen socket is bound to localhost. No remote attach over the network — that's a deliberate security boundary.
- **One client at a time.** debugpy accepts a single attach. If VS Code disconnects, the debuggee exits.

### When to use listen mode

- Pairing with a human at a workstation
- You need rich UI: variable hover, watch windows, call-stack click-through
- You're explaining a bug live and want them to see your stops

### When *not* to use listen mode

- Solo debugging — CLI is faster
- Headless / CI / sandbox environments without VS Code
- You need to script the debug session (CLI eval/step is scriptable; VS Code UI isn't)

## Combined Pattern — Best of Both

```powershell
# 1. CLI: hunt down the suspect region with conditional bps
dbga session start --break-at "loader.py:30:not records" --use-bps-file -- runner.py
dbga session eval --expr "source_path"
dbga session set-bp loader.py:18
dbga session list-bp
dbga session release            # set-bp writes persist to .debug-agent/breakpoints.json

# 2. Open VS Code, sync bps from the file, run again under --listen
dbga session start --listen 5678 --use-bps-file -- runner.py

# 3. Attach VS Code → step through visually with watch windows
```

You used the CLI's strength (scriptable, fast hypothesis testing) to narrow the search, then the IDE's strength (visual inspection of complex state) to confirm.

## Troubleshooting

- **VS Code attaches but immediately disconnects.** Usually a version mismatch between debugpy in your venv and what VS Code's Python extension expects. Confirm: `python -c "import debugpy; print(debugpy.__version__)"` matches the extension's requirements.
- **`address already in use`.** Another process is on port 5678. Pick a different port (`--listen 5679`) or find the offender with `netstat -ano | findstr :5678` on Windows.
- **Breakpoints set in CLI not appearing in VS Code.** VS Code doesn't read `.debug-agent/breakpoints.json` natively — you need a sync step. See the handoff example above.
- **Listen mode started but VS Code can't attach.** Listen-mode sessions don't show up in `sessions ls` (no daemon). Check the PID returned in the `start` response (e.g. `Get-Process -Id <pid>`) — if it's gone, the debuggee exited before attach. Re-run `session start --listen` and connect promptly.
