# Agent teams — parallel competing-hypothesis debugging (experimental)

An optional, advanced wiring for the `architect`. Default orchestration is the
main-thread architect dispatching one expert at a time (see `architect.md`).
Reach for teams only when a bug has **several plausible independent causes** and
you want experts to chase them in parallel rather than in sequence.

## When it helps

- A hard, non-deterministic bug (hang, race, flaky test) with 2–3 competing
  hypotheses that can be investigated independently.
- A cross-language failure where Python, Go, and Node experts can each gather
  evidence on their own surface at the same time.

If one hypothesis clearly dominates, don't bother — sequential delegation is
simpler and cheaper.

## How to enable

Agent teams are gated behind an experimental flag:

```sh
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1   # POSIX
$env:CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"  # Windows PowerShell
```

Run the architect as the main thread so it can coordinate the team:

```sh
claude --agent debug-agent:architect
```

## Platform note

- **POSIX:** teammates can run as separate coordinated processes.
- **Windows:** runs in **in-process mode** — teammates execute within the lead's
  process. Functionally equivalent for this workflow; expect less true
  parallelism.

This is an experimental Claude Code capability and its surface may change. If
the flag is unset or unsupported, the architect transparently falls back to
sequential one-expert-at-a-time delegation — nothing breaks.

## The loop with a team

1. Architect frames the bug and enumerates the competing hypotheses.
2. Each teammate (the matching language expert) takes one hypothesis and gathers
   runtime evidence with `dbga` / the `debug-agent` skill — no guessing.
3. Architect collects the evidence, picks the hypothesis the evidence supports,
   and has the owning expert implement the fix.
4. Verify at the original fault before closing — same rule as the default loop.
