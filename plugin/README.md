# debug-agent — Claude Code plugin

Evidence-first debugging for **Python, Go, and Node/TypeScript** over DAP, plus
consolidated per-language development skills and an `architect` to orchestrate a
complete **design → develop → debug deeply → verify → clean up** workflow.

The plugin bundles the `dbga` debugger driver skill with three language skills
and four agents, all enforcing the same principles: validate against real flows,
debug with the toolkit instead of guessing, keep dependencies fresh, and ship
clean, self-explaining code.

## Name glossary

Three names, three contexts — they refer to the same project:

| Name | Where it appears |
| --- | --- |
| `dbga` | The marketplace name and the installed CLI binary (`dbga --version`). |
| `debug-agent` | The plugin name and its command/skill namespace (`/debug-agent:*`). |
| `debug_agent` | The Python import / distribution module name. |

## What's inside

- **Skills** (`/debug-agent:*`): `debug-agent` (the `dbga` driver), `python`,
  `go`, `node`.
- **Agents** (`/agents`): `architect` (opus, orchestrator), `python-expert`,
  `go-expert`, `node-expert`.
- **Command:** `/debug-agent:setup` — optional one-shot `dbga` installer.

## Install — full plugin (recommended)

Adds all skills, agents, and the setup command.

```sh
claude plugin marketplace add niradler/dbga
/plugin install debug-agent@dbga
```

Then run the optional installer to put `dbga` on your PATH:

```sh
/debug-agent:setup
```

…or install `dbga` yourself:

```sh
uv tool install dbga   # or: pipx install dbga   # or: pip install --user dbga
dbga --version
```

## Install — a single skill

The [`skills`](https://github.com/vercel-labs/skills) CLI installs any one skill
standalone (skills only — agents and commands come with the full plugin):

```sh
npx skills add niradler/dbga --skill python   # or: go | node | debug-agent
npx skills add niradler/dbga --list           # preview what's available
```

Resolution is automatic: the repo-root `.claude-plugin/marketplace.json` points
the `skills` CLI at `plugin/skills/`, so no `--full-depth` flag is needed.

## Usage

- **Just debug:** invoke the `debug-agent` skill (or run `dbga`) when something
  crashes, hangs, or returns wrong output.
- **Develop in one language:** the matching skill (`python`/`go`/`node`) loads
  language-specific references on demand.
- **Orchestrate:** run `claude --agent debug-agent:architect` to let the
  architect gather evidence and delegate to the language experts. Delegation
  works **only when the architect is the main agent** — dispatched as a subagent
  it cannot spawn experts and works solo. See
  [`references/agent-teams.md`](references/agent-teams.md) for the experimental
  parallel-debugging mode.
- **Hard single-language task:** the experts default to **sonnet**; for a gnarly
  type-level, concurrency, or panic-trace problem, request an **opus** override
  at dispatch.
- **Review vs. debug:** on a live failure the agents reproduce it with `dbga`
  before proposing a fix. On a review/audit task (no failing run) they reason
  from source but label each finding `RUNTIME-VERIFIED` vs `INSPECTION-ONLY` —
  treat an `INSPECTION-ONLY` finding as a hypothesis until you've run it.

## License

MIT — see [`LICENSE`](LICENSE). Upstream attributions in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
