# Design: `debug-agent` Claude Code Plugin

Date: 2026-05-29
Status: Final — ready for implementation plan
Owner: Nir

## Goal

Package the `dbga` evidence-first debugger plus a consolidated set of
language skills and specialist agents as a distributable **Claude Code
plugin**, giving a complete **design → develop → debug deeply → verify →
clean up** workflow for Python, Go, and Node.

Two install paths must both work cleanly:

1. **Full plugin** via marketplace —
   `claude plugin marketplace add niradler/dbga` then
   `/plugin install debug-agent@dbga`.
2. **Single skill** via the `skills` CLI —
   `npx skills add niradler/dbga --skill python` (or `go`, `node`,
   `debug-agent`).

## Final shape

**4 agents** and **4 skills** — one consolidated skill + one expert per
language, an `architect` to orchestrate, and the debugger skill.

### Agents (`agents/*.md`)

| Agent | Model | Scope |
| --- | --- | --- |
| `architect` | **opus** | Language-agnostic. Owns high-level design, decomposition, cross-cutting decisions, and the evidence-first orchestration loop: gather runtime evidence → delegate language work to the matching expert → verify against real flows. Delegates; rarely writes code itself. |
| `python-expert` | sonnet (architect may override to opus for hard tasks) | Full Python specialist. Drives the `python` + `debug-agent` skills. |
| `go-expert` | sonnet (overridable) | Full Go specialist. Drives the `go` + `debug-agent` skills. |
| `node-expert` | sonnet (overridable) | TypeScript-focused (small JS-fallback section). Drives the `node` + `debug-agent` skills. |

There is no separate `code-reviewer` agent: clean-code review is a
cross-cutting responsibility every agent carries (see Working Principles) and
is backed by each skill's `clean-code` reference.

### Skills (`skills/*/SKILL.md`)

| Skill | Role |
| --- | --- |
| `python` | Main Python development skill. SKILL.md routes to many reference files (progressive disclosure). |
| `go` | Main Go development skill + references. |
| `node` | Main Node/TypeScript development skill + references. |
| `debug-agent` | Existing evidence-first `dbga` driver (Python/Go/Node over DAP). Moved into the plugin. |

Each skill is **self-contained** → any one installs cleanly on its own via
`npx skills`. Agents are plugin-only (the `skills` CLI installs skills, not
agents) — expected and documented.

## Source material & licensing

We **combine and learn from both** MIT-licensed sources — the goal is the
best result, not fidelity to any one repo:

- **wshobson/agents** (MIT) — has both agents and skills. Supplies the
  per-topic skill content (design-patterns, code-style, error-handling, async,
  anti-patterns, concurrency) and lean specialist agents.
- **VoltAgent/awesome-claude-code-subagents** (MIT) — agents only, but deep
  (e.g. `python-pro` ≈ 3,800 words: operational checklists, type-system
  mastery, async, testing methodology, security, collaboration protocol).

Combination rules:

1. **Each language skill** consolidates the relevant wshobson skills as
   **language-specific reference files**, enriched with the matching deep
   sections harvested from VoltAgent's agents. Language-**invariant** content
   (clean-code/no-comments, evidence-first discipline, dependency-hygiene
   discipline) is authored **once** in `skills/_shared/` and cross-referenced
   by name — never triple-copied across python/go/node.
2. **Each expert agent** merges the VoltAgent + wshobson versions of that
   language (VoltAgent depth + wshobson structure), deduplicated, then points
   at its skill + the `debug-agent` skill.
3. The `architect` agent is **authored fresh** (no single upstream
   equivalent), distilling the cross-cutting orchestration + working
   principles below.
4. Preserve upstream LICENSE/attribution; record the source commit SHA of each
   vendored file.

## Working principles (embedded in every agent + each skill's SKILL.md)

These are the non-negotiables the whole plugin enforces:

1. **Evidence and validation first.** Decisions are made by validating against
   **real use flows run against the code** — not by reasoning about source.
   Use logs, debugger breakpoints (`dbga`), and common practices to observe
   what actually happens. Never declare a fix done until correct behavior is
   **observed** at the point the bug occurred.
2. **Debug with the toolkit, don't guess.** On a crash/hang/wrong-output,
   reach for the `debug-agent` skill and `dbga` (diagnose, live sessions,
   `eval`, instrument) before sprinkling prints or guessing fixes.
3. **Proactive dependency hygiene.** On new install/setup and when touching
   dependencies, push to latest and audit proactively, then suggest bumps:
   - Node: `npm outdated`, `npm audit`, `npm install <pkg>@latest`.
   - Python: `uv lock --upgrade` / `uv pip install -U`, `pip-audit`.
   - Go: `go list -u -m all`, `go get -u ./...`, `govulncheck ./...`.
4. **Clean, self-explaining code** (mirrors the official `code-simplifier`):
   - Readable and **explicit over compact**; clarity beats brevity.
   - **Never add code comments unless explicitly asked.** Code should explain
     itself through clear names and structure. Remove comments that restate
     obvious code.
   - Avoid nested ternaries; prefer if/else or switch for multiple conditions.
   - Reduce nesting and redundancy; consolidate related logic.
   - Preserve functionality; don't over-simplify or strip helpful
     abstractions.
5. **Deliver clean, working, verified code — always.** The loop is design →
   implement → run real flows → debug with evidence → simplify → verify.
6. **Token economy.** These files are read by an agent, not a human. Slim,
   to-the-point, minimum words while keeping what's vital. Authoring
   constraints below enforce this.

## Authoring constraints (slim, agent-facing — from writing-skills)

Every skill and agent in this plugin follows:

- **SKILL.md is the slim index, not the manual.** Target < 500 words; route to
  `references/*.md` via progressive disclosure. Heavy/per-topic detail lives in
  references, loaded only when needed.
- **Descriptions are triggers only.** Third person, start with "Use when…",
  list symptoms/contexts. **No workflow summary** (a summarized description
  makes the agent skip the body).
- **Names:** lowercase, hyphenated, active (`python`, `go`, `node`,
  `debug-agent`; reference files like `error-handling`, `clean-code`).
- **Keyword coverage** for discovery (errors, symptoms, tool/command names).
- **Cross-reference by name**, not `@path` (no force-loading). Reference the
  matching expert agent and `debug-agent` skill where relevant.
- **One excellent example per pattern**, not many; no multi-language dilution.
- **Agents are concise too** — operational checklist + when-to-delegate, detail
  deferred to the skills they drive rather than restated inline.

A short version of principles 1–2 is injected as a standard **Evidence-First
Debugging** block in each agent/skill body:

```markdown
## Evidence-First Debugging (debug-agent toolkit)

You have `dbga` — an evidence-first debugger for Python/Go/Node over DAP —
and the `debug-agent` skill. When code crashes, hangs, produces wrong output,
or you need live runtime state, DO NOT guess from source. Gather evidence:

- `dbga diagnose -- <cmd>`  → triage a crash to the deepest user frame
- `dbga session start --break-at file:line -- <script>` then
  `dbga session eval --expr "<x>"` → inspect live state
- Invoke the `debug-agent` skill for the full evidence-first loop.

Validate against real use flows and verify the fix at the original fault
before declaring it done.
```

## Repository layout

```text
debug-cli/                          # repo root (existing Python project)
├── .claude-plugin/
│   └── marketplace.json            # one entry, source ./plugin
├── plugin/                         # PLUGIN ROOT
│   ├── .claude-plugin/
│   │   └── plugin.json             # name: debug-agent, namespace /debug-agent:*
│   ├── README.md                   # install + usage for both paths
│   ├── LICENSE                     # plugin MIT
│   ├── THIRD_PARTY_NOTICES.md      # verbatim upstream MIT notices + SHAs
│   ├── skills/                     # CANONICAL skills home (single source of truth)
│   │   ├── debug-agent/            # MOVED from repo-root skills/debug-agent/
│   │   │   ├── SKILL.md
│   │   │   └── references/         # existing: workflow, debugger, instrumentation, ...
│   │   ├── _shared/                  # language-invariant, authored ONCE
│   │   │   ├── clean-code.md          # self-explaining, no-comments rule
│   │   │   ├── evidence-first.md      # the debugging/validation discipline
│   │   │   └── dependency-hygiene.md  # audit-then-suggest discipline
│   │   ├── python/
│   │   │   ├── SKILL.md
│   │   │   └── references/            # PYTHON-SPECIFIC deltas only
│   │   │       ├── design-patterns.md # + idioms / anti-patterns
│   │   │       ├── type-hints.md
│   │   │       ├── async-concurrency.md
│   │   │       ├── errors-structure.md
│   │   │       └── debugging.md       # Python dbga recipes
│   │   ├── go/
│   │   │   ├── SKILL.md
│   │   │   └── references/
│   │   │       ├── design-patterns.md
│   │   │       ├── concurrency.md     # goroutines, channels, sync
│   │   │       ├── errors-structure.md
│   │   │       └── debugging.md       # Go dbga + dlv recipes
│   │   └── node/
│   │       ├── SKILL.md
│   │       └── references/
│   │           ├── design-patterns.md
│   │           ├── typescript-types.md
│   │           ├── async-patterns.md
│   │           ├── errors-structure.md
│   │           ├── js-fallback.md
│   │           └── debugging.md       # Node dbga + vscode-js-debug recipes
│   ├── agents/
│   │   ├── architect.md             # opus, language-agnostic orchestrator
│   │   ├── python-expert.md
│   │   ├── go-expert.md
│   │   └── node-expert.md
│   ├── commands/
│   │   └── setup.md                 # /debug-agent:setup (optional one-shot installer)
│   └── references/
│       └── agent-teams.md           # optional advanced parallel-debugging mode
└── ...                              # src/, tests/, pyproject.toml, etc.
```

Rationale for canonical skills under `plugin/skills/`:

- The plugin manifest loads every skill in that dir automatically.
- `npx skills add` scans the cloned repo for a `SKILL.md` by skill name at any
  depth (confirmed by existing wshobson usage where skills live deeply nested),
  so a single-skill install resolves from the same dir. **No duplication.**
- The existing `skills/debug-agent/` is **moved** here; the one reference in
  the repo `CLAUDE.md` is updated.

## Orchestration & collaboration

**Constraint (verified):** a subagent cannot spawn subagents. So `architect`
**cannot** be a passively-delegated subagent that itself calls the experts.
Two valid wirings, both opt-in:

1. **Architect as the main thread** — `claude --agent debug-agent:architect`.
   Running as the main thread, it *can* dispatch `python-expert` / `go-expert`
   / `node-expert` as subagents (with a per-call `model` override for hard
   tasks). This is the default orchestration path. We do **not** force it via
   the plugin `settings.json` `agent` key — that would hijack every session;
   it's user-invoked.
2. **Architect as an agent-teams lead** — for parallel competing-hypothesis
   debugging, documented in `references/agent-teams.md` (experimental
   `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`; Windows = in-process mode).

The loop in either wiring: detect language → gather evidence via
`debug-agent`/`dbga` → fix via the matching expert → verify at the original
fault that the code is clean and self-explaining.

If a user never invokes `architect`, the experts and skills still work
directly — the main session drives them. Architect is the orchestration
convenience, not a hard dependency.

## Install handling (dbga is not pip-installed by the plugin)

Kept deliberately minimal — **no hooks, no PATH launchers, no background
checks.** Just one optional command plus a README line.

- **`/debug-agent:setup`** command (optional convenience): install `dbga`
  (prefer `uv tool install dbga`, fall back to `pipx install dbga`, then
  `pip install --user dbga`), print `dbga --version` to confirm, and note any
  missing Go (`dlv`) / Node (vscode-js-debug) toolchain with the install
  command. Does not auto-install language toolchains.
- The skills already tell the agent to run `dbga --version` first (existing
  `debug-agent` SKILL.md). A missing binary surfaces there naturally — no hook
  needed.
- README documents the one-liner for users who skip the command.

## Manifest sketches

`plugin/.claude-plugin/plugin.json`:

```json
{
  "name": "debug-agent",
  "description": "Evidence-first debugging (Python/Go/Node over DAP) plus consolidated language skills and an architect to deliver clean, verified code.",
  "version": "0.1.0",
  "author": { "name": "Nir Adler" },
  "homepage": "https://github.com/niradler/dbga",
  "repository": "https://github.com/niradler/dbga",
  "license": "MIT"
}
```

`.claude-plugin/marketplace.json` (repo root):

```json
{
  "name": "dbga",
  "owner": { "name": "Nir Adler" },
  "plugins": [
    { "name": "debug-agent", "source": "./plugin" }
  ]
}
```

## Testing / verification

Functional:

- `claude plugin validate ./plugin` passes.
- `claude --plugin-dir ./plugin` loads; `/help` lists `/debug-agent:*` skills;
  `/agents` lists `architect`, `python-expert`, `go-expert`, `node-expert`.
- `npx skills add <local-or-repo> --skill python` installs one skill
  standalone (repeat for `go`, `node`, `debug-agent`).
- `/debug-agent:setup` installs `dbga` and reports version on a clean machine.
- `wc -w` each SKILL.md (except `debug-agent`) against the word targets above.

Behavioral (subagent scenarios, per writing-skills):

- End-to-end: architect on a known-buggy Python script → evidence via
  `debug-agent` → fix via `python-expert` → verified at the original fault,
  no stray comments, clean code.
- Each language skill: a subagent given a relevant task finds and applies the
  right reference file.
- Clean-code rule under pressure: a subagent does **not** add explanatory
  comments unless asked.

## Eval framework (lean — dev aid, not a 4× release gate)

Skim from the full skill-creator loop to the pieces that pay off:

1. **Behavioral subagent scenarios for all 4 skills** (the writing-skills
   RED/GREEN core) — the three scenarios in Testing above. Cheap, highest
   value.
2. **One shared description-trigger optimization run** across all four
   `description`s with a single ~20-query set whose negatives are the
   cross-skill near-misses (python vs go vs node vs debug-agent). Mis-trigger
   between the four is a single multi-class problem — one run, not four.
3. **Full quantitative benchmark only for `debug-agent` + `python`** (richest
   objective assertions). Go/Node are ported by analogy and spot-checked.

Run eval scripts through a POSIX shell (Bash tool / WSL), use
`generate_review.py --static`, and read `run_loop`'s `best_description` JSON
directly. Eval is a dev aid; a positive with-skill delta is a goal, not a hard
ship-gate for v0.1.

Representative assertions (grading.json fields: `text`/`passed`/`evidence`):
"added no code comments unless asked", "ran the real flow / debugger before
proposing a fix", "loaded the correct reference file", "suggested a dependency
bump when deps were stale".

**Self-improvement (borrowed from SkillOpt, not adopted).** SkillOpt
(MS, MIT, but 6 days old, benchmark-shaped, no SKILL.md/frontmatter or
description-trigger model) isn't worth wiring in as a dependency. Its *idea*
is: an optimizer-LLM proposes **bounded edits** to a skill doc, accepted
**only on strict improvement against a held-out split**, with versioned
`best`. That's complementary to `run_loop` (which only tunes the
`description` trigger). Decision: keep `run_loop` for triggers; **optionally
(v0.2+)** add a thin accept-on-improvement loop over our own
`evals.json` + with-skill harness to refine SKILL.md/reference **bodies** —
reimplemented in ~a script, not via the SkillOpt package.

## Decisions

- **Nested skill resolution — VERIFIED 2026-05-29 (skills CLI v1.5.0).**
  Resolves cleanly at **default depth, no `--full-depth` needed**. Mechanism:
  the skills CLI (`dist/cli.mjs` `getPluginSkillPaths`/`discoverSkills`) reads
  the repo-root `.claude-plugin/marketplace.json`, and for each plugin pushes
  `<source>/skills` (here `plugin/skills`) into its **priority search dirs**,
  scanning one level deep — so `plugin/skills/<name>/SKILL.md` is found by
  `npx skills add niradler/dbga --skill python`. Empirically: with no
  `marketplace.json`, a probe at `plugin/skills/probe/` was invisible at
  default depth; after adding `marketplace.json` with `source: "./plugin"` it
  resolved immediately. No per-skill `skills` array in the manifest required
  (that is an additional, optional override the CLI also honors). `_shared/`
  has no `SKILL.md`, so it is correctly skipped by the scan.
- **Vendor attribution — DECIDED.** Ship `plugin/THIRD_PARTY_NOTICES.md` with
  each upstream's verbatim MIT text + copyright line + repo URL + commit SHA,
  and a per-file header on files that are substantially copied. SHA alone is
  not MIT compliance.
- **Per-task model — DECIDED.** Agent definitions take a single `model`
  (architect=opus, experts=sonnet). Per-call `model` override at dispatch
  handles "opus for hard tasks" — valid only on the main-thread architect path
  (see Orchestration).
- **Skill move blast radius — DECIDED.** `skills/debug-agent/` is referenced in
  `CLAUDE.md`, `CHANGELOG.md`, and `README.md` (×3) — **5 references, not 1.**
  All updated on move; add a CHANGELOG "skill relocated" note. Verify
  `git check-ignore` does not swallow `.claude-plugin/` (`.gitignore` has
  `.claude/`).
- **Existing `debug-agent` SKILL.md is exempt** from the <500-word index rule —
  it's a validated driver doc (~1,400 words), not a routing index. Don't rewrite
  what works to hit a target.
- **Stale doc fixed.** Update repo `CLAUDE.md` "Python-only by design today"
  to reflect the merged multi-language reality (Go/Delve, Node/vscode-js-debug),
  matching the skill's "Honest Limits".
- **Scope: build all at once** (4 skills + 4 agents + lean eval), single
  `0.1.0` release.

## Build approach

Parallelize authoring with **one subagent per language**:

- 3 language subagents (Python, Go, Node) each own: pull the wshobson skill
  refs + VoltAgent agent for that language, merge/dedup, write the consolidated
  `<lang>` SKILL.md (slim index) + language-specific reference files, write the
  `<lang>-expert` agent, cross-reference `skills/_shared/` + `debug-agent`,
  inject the Evidence-First block, and draft that skill's `evals.json`.
- Main thread owns the shared, sequential pieces: `skills/_shared/*`, the
  `architect` agent, moving `debug-agent` + fixing its 5 references, the
  manifests, `THIRD_PARTY_NOTICES.md`, `/debug-agent:setup`, README, and the
  CLAUDE.md fix.
- Each subagent works in non-overlapping paths (`plugin/skills/<lang>/` +
  `plugin/agents/<lang>-expert.md`) to avoid write conflicts.
