# debug-agent Plugin — Implementation Plan (high-level)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.
> **This is a borrow-and-refine plan, not from-scratch.** Tasks state the goal, the source material to pull, refinement directives, and acceptance criteria. **The executing subagent decides the specific edits** — what to copy, cut, merge, and reword — within those boundaries. Do not expect prescribed line-by-line code.

**Goal:** Ship a Claude Code plugin `debug-agent` bundling the existing `dbga` debugger skill + 3 consolidated language skills (Python/Go/Node) + 4 agents (architect + 3 experts), installable as a full plugin and as single skills via `npx skills`.

**Architecture:** Plugin lives at `plugin/` with `.claude-plugin/marketplace.json` at repo root. Canonical skills under `plugin/skills/`; language-invariant content in `skills/_shared/`; agents in `plugin/agents/`. Content is merged from wshobson/agents + VoltAgent (both MIT) and refined with our Evidence-First + clean-code principles.

**Tech stack:** Markdown SKILL.md + agent definitions; `dbga` (Python CLI); skill-creator eval harness; `npx skills` CLI; `claude plugin validate`.

**Spec:** `docs/superpowers/specs/2026-05-29-debug-agent-plugin-design.md` — read it before starting; it holds the principles, layout, and decisions every task must honor.

---

## Phase 0 — De-risk first (do before anything else)

### Task 0: Verify `npx skills` resolves the planned layout
**Why first:** the whole canonical-skills-under-`plugin/skills/` decision rests on this. The `skills` CLI does NOT scan arbitrary depth by default.
- Create a throwaway `plugin/skills/probe/SKILL.md` and run `npx skills add <local-clone-or-path> --skill probe`.
- **Acceptance:** resolves cleanly. If it does NOT, switch to declaring skills in the manifest (or `--full-depth`) and record the chosen mechanism in the spec's Decisions section before proceeding. Delete the probe.

---

## Phase A — Plugin skeleton (main thread, sequential)

### Task 1: Scaffold plugin + manifests
**Files:** `plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (repo root), `plugin/README.md`, `plugin/LICENSE`, `plugin/THIRD_PARTY_NOTICES.md`.
- Use the manifest sketches in the spec verbatim as the starting point.
- README documents BOTH install paths + the name glossary (`dbga` marketplace / `debug-agent` plugin / `debug_agent` import).
- `THIRD_PARTY_NOTICES.md`: placeholder structure now; subagents fill upstream MIT text + SHA per file they vendor.
- **Acceptance:** `claude plugin validate ./plugin` passes; `claude --plugin-dir ./plugin` loads with no errors.

### Task 2: Move the `debug-agent` skill into the plugin
**Scope:** move `skills/debug-agent/` → `plugin/skills/debug-agent/` (keep its references intact). Update **all 5** references: `CLAUDE.md`, `CHANGELOG.md`, `README.md` (×3).
- Verify `git check-ignore -v plugin/.claude-plugin/plugin.json` does NOT match `.gitignore`'s `.claude/`.
- **Acceptance:** repo test suite still green (`uv run pytest -m "not e2e"`); the moved skill loads under the plugin; existing `npx skills add … --skill debug-agent` documented against the new path.
- **Exempt** this SKILL.md from the <500-word rule — do not rewrite it.

### Task 3: Author `skills/_shared/`
**Files:** `plugin/skills/_shared/{clean-code,evidence-first,dependency-hygiene}.md`.
- Language-invariant only. clean-code = self-explaining, no-comments-unless-asked (mirror `code-simplifier` philosophy). evidence-first = the validation/debug discipline + the canonical Evidence-First block (single source of truth). dependency-hygiene = audit-then-**suggest** (mark mutating commands as suggest-only, never auto-run).
- **Acceptance:** the three files exist, are concise, and are the only home for this content (language skills will cross-reference them by name).

### Task 4: Author the `architect` agent
**Files:** `plugin/agents/architect.md` (model: opus).
- Orchestration loop per spec; wired as opt-in main-thread agent (NOT forced via settings.json `agent` key). Allowed to dispatch the experts with per-call model override. Concise: checklist + when-to-delegate, defers detail to skills.
- **Acceptance:** appears in `/agents`; running `claude --agent debug-agent:architect` lets it dispatch an expert.

### Task 5: `/debug-agent:setup` command + Task 6: `references/agent-teams.md` + Task 7: fix CLAUDE.md
- T5: `plugin/commands/setup.md` — optional installer (uv → pipx → pip fallback), prints `dbga --version`, notes missing Go/Node toolchains. **Acceptance:** `/debug-agent:setup` installs and confirms version.
- T6: `plugin/references/agent-teams.md` — document the experimental teams path (Windows = in-process). **Acceptance:** file present, accurate.
- T7: update repo `CLAUDE.md` "Python-only by design today" to the merged multi-language reality, matching the skill's Honest Limits. **Acceptance:** line no longer contradicts the shipped Go/Node support.

---

## Phase B — Per-language (one subagent each, parallel, non-overlapping paths)

> Dispatch 3 subagents — Python, Go, Node. Each owns ONLY `plugin/skills/<lang>/**` and `plugin/agents/<lang>-expert.md`. **Each subagent figures out exactly what to borrow and how to refine it** within the directives below.

### Task 8 / 9 / 10: Build `<lang>` skill + `<lang>-expert` agent
**Sources to pull (MIT):**
- Python: wshobson `python-development` skills (design-patterns, anti-patterns, code-style, error-handling, async, project-structure) + agent `python-pro`; VoltAgent `python-pro` depth.
- Go: wshobson `systems-programming/go-concurrency-patterns` + agent `golang-pro`; VoltAgent `golang-pro`.
- Node: wshobson `javascript-typescript` skills (modern-js, ts-advanced-types, nodejs-backend, js-testing) + agents `typescript-pro`/`javascript-pro`; VoltAgent `typescript-pro` (primary) + `javascript-pro` (JS-fallback section only).

**Directives:**
- Write `plugin/skills/<lang>/SKILL.md` as a **slim index (<500 words)** routing to `references/` (language-specific deltas only — see spec layout). Cross-reference `skills/_shared/*` and `debug-agent` **by name**; do NOT copy their content.
- Write language-specific reference files (design-patterns, concurrency/async, types where relevant, errors-structure, debugging recipes with `dbga`).
- Write `plugin/agents/<lang>-expert.md` (model: sonnet) — merge VoltAgent depth + wshobson structure, dedup, inject the Evidence-First block, point at its skill. Concise; no restating reference content.
- `description` = triggers only ("Use when…"), no workflow summary, keyword-rich.
- Add upstream MIT notice + SHA to `THIRD_PARTY_NOTICES.md` for files substantially copied.
- Draft `plugin/skills/<lang>/evals/evals.json` (2–3 realistic prompts).
- **Acceptance:** skill loads as `/debug-agent:<lang>`; `wc -w SKILL.md` < 500; expert in `/agents`; references present; evals.json present; no duplication of `_shared` content.

---

## Phase C — Eval + final verification

### Task 11: Behavioral scenarios (all 4 skills)
- Run the 3 subagent scenarios from the spec (e2e architect→debug→fix→verify; correct-reference retrieval; no-comments-under-pressure) via the skill-creator baseline-vs-with-skill pattern, through a POSIX shell, `generate_review.py --static`.
- **Acceptance:** with-skill beats baseline on the no-comments + evidence-first assertions; gaps fed back into the skills.

### Task 12: One shared description-trigger optimization
- Single ~20-query set (negatives = cross-skill near-misses python/go/node/debug-agent); run `run_loop`; apply each `best_description`.
- **Acceptance:** the four skills fire on their own intent and stay quiet on the others'.

### Task 13: Full benchmark for `debug-agent` + `python` only
- aggregate_benchmark → review. Go/Node spot-checked, not full-looped.
- **Acceptance:** positive with-skill delta recorded (goal, not hard gate).

### Task 14: Release verification
- `claude plugin validate ./plugin`; `--plugin-dir` load; `/help` lists `/debug-agent:*`; `/agents` lists architect + 3 experts; `npx skills add <clone> --skill python|go|node|debug-agent` each install standalone; e2e architect loop on a known-buggy script.
- **Acceptance:** all pass; tag `0.1.0`.

---

## Notes
- Frequent commits per task on `feat/claude-plugin`.
- No AI attribution in commits/PRs (per user rules).
- Each Phase-B subagent works in isolated paths to avoid write conflicts; the main thread merges `THIRD_PARTY_NOTICES.md` additions if they touch the same file.
