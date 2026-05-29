"""Unit tests for the language-adapter registry and detection logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from debug_agent.adapters import (
    detect_language,
    get_adapter,
    list_adapters,
    resolve_language,
)
from debug_agent.adapters.python import PythonAdapter


def test_python_adapter_is_registered() -> None:
    assert "python" in list_adapters()


def test_get_adapter_returns_python_instance() -> None:
    adapter = get_adapter("python")
    assert isinstance(adapter, PythonAdapter)
    assert adapter.name == "python"


def test_get_adapter_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown language"):
        get_adapter("brainfuck")


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("foo.py", "python"),
        ("dir/sub/main.py", "python"),
        (Path("foo.py"), "python"),
        ("foo.txt", None),
        ("noext", None),
        (None, None),
    ],
)
def test_detect_language(script: str | Path | None, expected: str | None) -> None:
    assert detect_language(script) == expected


def test_resolve_language_explicit_wins() -> None:
    assert resolve_language(explicit="python", script="foo.go") == "python"


def test_resolve_language_unknown_explicit_raises() -> None:
    with pytest.raises(ValueError, match="unknown --lang"):
        resolve_language(explicit="lolcode", script="foo.py")


def test_resolve_language_falls_back_to_detection() -> None:
    assert resolve_language(explicit=None, script="app.py") == "python"


def test_resolve_language_default_when_undetectable() -> None:
    assert resolve_language(explicit=None, script="noext", default="python") == "python"
    assert resolve_language(explicit=None, script=None, default="python") == "python"


def test_python_adapter_launch_payload_shape() -> None:
    adapter = get_adapter("python")
    payload = adapter.launch_payload(
        script=Path("script.py"),
        args=["a", "b"],
        cwd=Path("/tmp/work"),
        stop_on_entry=True,
    )
    assert payload["type"] == "python"
    assert payload["request"] == "launch"
    assert payload["stopOnEntry"] is True
    assert payload["args"] == ["a", "b"]
    assert payload["cwd"] == "/tmp/work" or payload["cwd"].endswith("work")
    # ``program`` is resolved to an absolute path.
    assert payload["program"].endswith("script.py")


def test_python_adapter_supports_listen_mode() -> None:
    adapter = get_adapter("python")
    assert adapter.supports_listen_mode() is True
    assert adapter.attach_url("127.0.0.1", 5678) == "debugpy://127.0.0.1:5678"


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        # ``python foo.py a b`` → peel interpreter
        (["python", "foo.py", "a", "b"], ("foo.py", ["a", "b"])),
        (["python3", "foo.py"], ("foo.py", [])),
        # ``py.exe`` (Windows launcher) is recognised too
        (["py.exe", "foo.py"], ("foo.py", [])),
        # Skip interpreter flags before the script
        (["python", "-O", "foo.py", "x"], ("foo.py", ["x"])),
        # ``-m foo`` has no launchable script path
        (["python", "-m", "mypkg"], None),
        # Non-interpreter command: treat cmd[0] as the program
        (["pytest", "tests/"], ("pytest", ["tests/"])),
    ],
)
def test_python_adapter_resolve_launch_target(
    cmd: list[str], expected: tuple[str, list[str]] | None
) -> None:
    adapter = get_adapter("python")
    assert adapter.resolve_launch_target(cmd) == expected


def test_python_adapter_parses_traceback() -> None:
    adapter = get_adapter("python")
    text = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 10, in <module>\n'
        "    do_thing()\n"
        '  File "foo.py", line 4, in do_thing\n'
        "    1 / 0\n"
        "ZeroDivisionError: division by zero\n"
    )
    parsed = adapter.parse_traceback(text)
    assert parsed.error_type == "ZeroDivisionError"
    assert len(parsed.frames) == 2
    assert parsed.deepest_user_frame is not None
    assert parsed.deepest_user_frame.line == 4


def test_probe_template_default_is_passthrough() -> None:
    adapter = get_adapter("python")
    assert adapter.probe_template(kind="log", code="print('x')") == "print('x')"


def test_only_node_delegates_launch_to_child() -> None:
    """Node delegates the launched program to a child session; Python/Go don't.

    Regression guard for the launch-breakpoint routing: ``DapSession`` keys
    its defer-and-replay-on-child behavior off this flag.
    """
    assert get_adapter("node").delegates_launch_to_child is True
    assert get_adapter("python").delegates_launch_to_child is False
    assert get_adapter("go").delegates_launch_to_child is False
