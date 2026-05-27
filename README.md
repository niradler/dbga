# debug-cli

An evidence-first Python debugger CLI for AI agents. Wraps `debugpy` to provide structured,
machine-readable debugging primitives (breakpoints, stepping, stack/variable inspection)
suitable for use by autonomous coding agents.

## Status

Alpha — under active development. APIs and CLI surface are not yet stable.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --all-extras
```

## Run

```sh
uv run debug-cli --version
```

## Develop

```sh
uv run pytest -v
uv run ruff check .
uv run mypy src
```
