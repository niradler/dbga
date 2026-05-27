from __future__ import annotations

import json

from debug_cli.core.format import format_json, format_text


def test_format_json_compact() -> None:
    result = format_json({"a": 1, "b": [1, 2]}, pretty=False)
    assert json.loads(result) == {"a": 1, "b": [1, 2]}
    assert "\n" not in result


def test_format_json_pretty() -> None:
    result = format_json({"a": 1}, pretty=True)
    assert "\n" in result


def test_format_text_simple_dict() -> None:
    result = format_text({"status": "ok", "duration_ms": 12})
    assert "status: ok" in result
    assert "duration_ms: 12" in result
