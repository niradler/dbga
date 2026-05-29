# Plugin simulation fixtures

Known-buggy programs used to exercise the `debug-agent` plugin (skills + agents
driving `dbga`) end-to-end in a realistic session. Not collected by pytest
(no `test_*.py`).

| Path | Bug | `dbga diagnose` should report |
| --- | --- | --- |
| `python/buggy_average.py` | divide by `len([])` | `ZeroDivisionError: division by zero`, deepest frame `average` line 3 |
| `go/buggy.go` | `total / len(nums)` on empty slice | `panic: runtime error: integer divide by zero`, `main.average` line 10 |
| `node/buggy.js` | `record.value` on a `null` element | `TypeError: Cannot read properties of null (reading 'value')`, `getValue` |

Each is the same "average of an empty collection" / "null element" class of bug,
so the fix is to guard the empty/null case before the operation.

## Reproduce

```sh
uv run dbga diagnose --timeout 30 -- python tests/plugin-sim/python/buggy_average.py
uv run dbga diagnose --lang go --cwd tests/plugin-sim/go --timeout 90 -- go run buggy.go
uv run dbga diagnose --cwd tests/plugin-sim/node --timeout 90 -- node buggy.js
```

If `diagnose` returns `session_exists`, clear the prior run first:
`uv run dbga session release`.
