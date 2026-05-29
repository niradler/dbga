# Trigger-separation eval — results (2026-05-29)

Lean dev-aid eval per the plugin spec (a goal, not a ship gate). Harness:
skill-creator `scripts/run_eval.py`, which installs a skill's `description` as a
temp command and runs `claude -p <query>` to see whether the model invokes it.

Query pool: `trigger-queries.json` — 16 queries, 4 per skill intent
(python / go / node / debug-agent). For each skill the same pool is relabeled
`should_trigger = (intent == skill)`, so the other 12 act as cross-skill
near-miss negatives.

## Results (WSL/Linux, skills CLI harness, runs-per-query 1–3)

| Skill | Passed | Negatives (no mis-trigger) | Positives (auto-trigger ≥0.5) |
| --- | --- | --- | --- |
| debug-agent | 12/16 | 12/12 ✅ | ~1/4 |
| python | 12/16 | 12/12 ✅ | ~0/4 |
| go | 13/16 | 12/12 ✅ | ~1/4 |
| node | 12/16 | 12/12 ✅ | ~0/4 |

- **Cross-skill separation (the property that matters for a 4-skill plugin):
  excellent and uniform.** Every skill stays quiet on the other three skills'
  intents (12/12 negatives each). No mis-trigger observed anywhere.
- **Positive auto-trigger rate is uniformly low — a harness ceiling, not a
  prompt defect.** Discriminating test: re-running `debug-agent` with a
  deliberately punchy, imperative description ("Use this skill whenever…",
  explicit trigger keywords, "Always use before guessing") produced **no lift**
  (still ~1/4). A description-quality problem would vary by skill and respond to
  a stronger trigger; instead the rate is flat across all skills and unresponsive
  to description strength. The cause is methodology: `run_eval.py` injects each
  skill as a `.claude/commands/` entry and measures whether one-shot `claude -p`
  auto-invokes it — and one-shot non-interactive runs tend to just do the task
  rather than auto-invoke a command. Real plugin-installed skills trigger via a
  different path.

## Why `run_loop` auto-optimization was not run

`run_loop` maximizes positive trigger rate. The discriminating test shows that
rate is capped by the harness, not the description, so optimization would chase
a biased proxy and risk overfitting descriptions that are already triggers-only,
keyword-rich, independently reviewed, and behaviorally validated (see the
buggy-script baseline-vs-with-skill test). Decision: keep the reviewed
descriptions; rely on the clean separation result.

## Windows note (original blocker)

On native Windows the positive axis was entirely unmeasurable: `run_eval.py`
polls the `claude -p` subprocess **pipe** with `select.select()`, and Windows
`select` accepts only sockets → `WinError 10038`. WSL/Linux fixes this (Linux
`select` works on pipe fds). Rerun under WSL with:

```sh
PYTHONPATH=<skill-creator> uv run --no-project --with pyyaml python run_eval.py \
  --eval-set <skill>.json --skill-path plugin/skills/<skill> --runs-per-query 3
```

(`--no-project` is required so `uv` does not try to repair the Windows-format
`.venv` over the `/mnt/c` mount.)
