# Evidence-first development & debugging

Language-invariant. The language skills and agents reference this by name — do
not copy it. This is the single source of truth for the discipline and the
standard **Evidence-First Debugging** block embedded across the plugin.

## The discipline

1. **Validate against real flows, not source-reading.** Decide what the code
   does by running a real use flow against it and observing the result — logs,
   debugger breakpoints, common practices. Reasoning about source is a
   hypothesis; a run is evidence.
2. **Debug with the toolkit, don't guess.** On a crash, hang, or wrong output,
   reach for the `debug-agent` skill and `dbga` *before* sprinkling prints or
   guessing fixes. A debugger stop returns full context in one round-trip;
   prints give you one value at a time.
3. **Verify at the original fault.** Never declare a fix done until you have
   **observed** correct behavior at the exact point the bug occurred — same
   breakpoint, same input, same assertion that previously failed.

The loop: design → implement → run the real flow → debug with evidence →
simplify → verify at the fault.

## Two modes: live-failure vs. static review

The discipline above assumes a *live failure to reproduce*. Match the mode to
the task:

- **Live failure** (crash, hang, wrong output, flaky test): reproduce it with
  `dbga` first. Source reasoning is a hypothesis until a run confirms it. Verify
  the fix at the original fault.
- **Static review / audit / design assessment** (no failing run to point at —
  "review this for bugs", "is this design sound"): source reasoning is
  legitimate, but it is *unverified*. So:
  1. **Label every finding** `RUNTIME-VERIFIED` (you reproduced/observed it) or
     `INSPECTION-ONLY` (read from source). Never imply verification you didn't do.
  2. **Prove or offer the repro.** If a finding can be shown with a failing test
     or a `dbga` run, do it — or explicitly offer it. A bug you could have run
     but didn't is INSPECTION-ONLY at best.
  3. **Separate "breaks today" from "latent."** Rank by what fails under the
     runtime in use now vs. only under a future/edge runtime (e.g. free-threaded
     CPython). Don't inflate severity for the theoretical.

A confident, well-formatted INSPECTION-ONLY finding is the most dangerous output
you produce — it reads as fact. The label and the repro offer keep it honest.

## Standard Evidence-First Debugging block

Embed this (verbatim or trimmed) in agents and skill bodies:

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
before declaring it done. On a **review/audit** task (no live failure to
reproduce), source reasoning is fine but unverified: label each finding
RUNTIME-VERIFIED vs INSPECTION-ONLY, prove or offer a repro for anything
reproducible, and separate "breaks today" from "latent under a future/edge
runtime."
```

## Mindset (cross-language)

- **Two strikes, rethink.** Two failed hypotheses at the same spot means your
  model is wrong — form a different theory aimed elsewhere.
- **Breakpoint where the problem *begins*,** not where it manifests. Walk up the
  stack to the frame where the value first went wrong.
- **Read-only eval.** Inspecting live state should not mutate it unless you're
  deliberately probing a fix.
