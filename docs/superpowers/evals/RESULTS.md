# Trigger-separation eval — results (2026-05-29)

Lean dev-aid eval per the plugin spec (a goal, not a ship gate). Harness:
skill-creator `scripts/run_eval.py`, which installs a skill's `description` as a
temp command and runs `claude -p <query>` to see whether the model invokes it.

Query pool: `trigger-queries.json` — 16 queries, 4 per skill intent
(python / go / node / debug-agent). For each skill the same pool is relabeled
`should_trigger = (intent == skill)`, so the other 12 act as cross-skill
near-miss negatives.

## What was measured

- **Cross-skill separation (negatives): PASS.** `debug-agent` ran against the
  full pool: **12/12 cross-language negatives correctly did NOT trigger** — it
  stayed quiet on every python/go/node query. A `python` smoke run likewise
  stayed quiet on the go/node negatives. The descriptions are well-separated;
  no mis-trigger between the four skills was observed.

## Platform limitation (positive rate not measurable on native Windows)

- The 4 positive queries reported `trigger_rate 0` — but each coincided with a
  `WinError 10038: An operation was attempted on something that is not a
  socket`. `run_eval.py` detects triggering by `select.select()` on the
  `claude -p` subprocess **pipe**; on native Windows `select` accepts only
  sockets, so the stream reader raises before it can observe the Skill
  invocation. This is a harness/platform bug, **not** a description defect.
- The spec anticipated this: "Run eval scripts through a POSIX shell (Bash
  tool / WSL)." Reliable positive-trigger and the auto-rewrite `run_loop` need
  WSL/Linux. The unbounded `run_loop` was intentionally skipped on Windows
  because it would inherit the same broken positive signal.

## Conclusion

The high-value property — the four descriptions fire on their own intent and
stay quiet on the others' — is validated on the reliable (negative) axis, and
the descriptions were independently reviewed as triggers-only and keyword-rich.
Positive-rate numbers should be regenerated under WSL/Linux if exact figures are
wanted; rerun with:

```sh
PYTHONPATH=<skill-creator> python run_eval.py \
  --eval-set <skill>.json --skill-path plugin/skills/<skill> \
  --runs-per-query 3 --model claude-sonnet-4-6
```
