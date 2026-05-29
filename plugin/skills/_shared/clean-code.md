# Clean, self-explaining code

Language-invariant. The language skills reference this by name — do not copy it.

## The rule

Code explains itself through names and structure. Mirrors the official
`code-simplifier`: clarity over cleverness, explicit over compact.

- **No comments unless explicitly asked.** A comment that restates the code is
  noise — delete it. If a line needs a comment to be understood, rename the
  symbols or extract a well-named function instead. Keep only comments that
  capture *why* a non-obvious choice was made and that the code genuinely cannot
  express (a workaround, an external contract, a deliberate constraint).
- **Readable over terse.** A clear `if/else` beats a dense one-liner. Optimize
  for the next reader, not character count.
- **No nested ternaries.** Use `if/else`, early returns, or a `switch`/`match`
  for more than two branches.
- **Reduce nesting.** Prefer guard clauses and early returns over deep `if`
  pyramids. Flatten happy-path code to the left margin.
- **Consolidate redundancy.** Pull repeated logic into one well-named place;
  don't duplicate a rule in three branches.
- **Names match behavior.** Name things for *what they do*, not *how*. Rename
  the moment a name drifts from its meaning.

## Don't over-simplify

Preserve functionality and helpful abstractions. Simplification removes
accidental complexity (noise, duplication, dead branches) — never essential
structure. If collapsing a layer would hide a real boundary or lose a tested
behavior, leave it.

## When touching existing code

Match the surrounding style — comment density, naming, idioms. Improve what you
touch the way a careful developer would; don't restructure beyond your task.

## Self-check before done

- Did I add any comment I wasn't asked for? Remove it.
- Could a rename or extraction replace an explanation?
- Is any branch nested more than necessary?
- Does every name still describe what the thing does?
