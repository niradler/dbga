# Dependency hygiene — audit, then suggest

Language-invariant. The language skills reference this by name — do not copy it.

## The rule

On new install/setup and whenever you touch dependencies, proactively audit and
push toward latest — then **suggest** the bumps. Never run a mutating command
(install, upgrade, lockfile rewrite) on your own; surface what you found and the
exact command, and let the developer run it.

- **Audit commands are safe to run** — they only read.
- **Mutating commands are suggest-only** — present them, don't execute them.
- Pin intent: explain *why* a bump matters (security advisory, bug fix, EOL)
  rather than upgrading blindly.

## Per language

### Node

- Audit (run): `npm outdated`, `npm audit`
- Suggest (don't run): `npm install <pkg>@latest`, `npm audit fix`

### Python

- Audit (run): `pip-audit`, `uv pip list --outdated`
- Suggest (don't run): `uv lock --upgrade`, `uv pip install -U <pkg>`

### Go

- Audit (run): `go list -u -m all`, `govulncheck ./...`
- Suggest (don't run): `go get -u ./...`, `go get <module>@latest`

## Reporting

Lead with anything from a vulnerability audit, then stale-but-safe bumps. For
each: package, current → available, the reason, and the suggest-only command.
If nothing is stale or vulnerable, say so in one line and move on.
