"""Unit tests for the Go adapter (registry + traceback parser + launch payload).

Integration-level tests that actually spawn ``dlv dap`` live in
``tests/integration/test_go_session.py`` and skip when delve isn't on PATH.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from debug_agent.adapters import detect_language, get_adapter, list_adapters
from debug_agent.adapters.go import GoAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tracebacks"


def test_go_adapter_registered() -> None:
    assert "go" in list_adapters()
    adapter = get_adapter("go")
    assert isinstance(adapter, GoAdapter)
    assert adapter.name == "go"


def test_go_extension_detection() -> None:
    assert detect_language("main.go") == "go"
    assert detect_language("cmd/server/main.go") == "go"


def test_go_launch_payload_shape() -> None:
    adapter = get_adapter("go")
    payload = adapter.launch_payload(
        script=Path("main.go"),
        args=["--port", "8080"],
        cwd=Path("/tmp/proj"),
        stop_on_entry=True,
    )
    assert payload["type"] == "go"
    assert payload["request"] == "launch"
    assert payload["mode"] == "debug"
    assert payload["stopOnEntry"] is True
    assert payload["args"] == ["--port", "8080"]
    # ``program`` resolved to an absolute path
    assert payload["program"].endswith("main.go")
    assert payload["cwd"].endswith("proj")


def test_go_attach_url_uses_dlv_dap_scheme() -> None:
    adapter = get_adapter("go")
    assert adapter.attach_url("127.0.0.1", 2345) == "dlv-dap://127.0.0.1:2345"


def test_go_supports_listen_mode() -> None:
    assert get_adapter("go").supports_listen_mode() is True


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        # ``go run main.go args`` → debug ``main.go``
        (["go", "run", "main.go"], ("main.go", [])),
        (["go", "run", "main.go", "--port", "8080"], ("main.go", ["--port", "8080"])),
        # Skip ``go run`` flags like ``-race``
        (["go", "run", "-race", "main.go", "x"], ("main.go", ["x"])),
        # ``go test`` is out of scope (needs mode:"test")
        (["go", "test", "./..."], None),
        # Pre-built binary: treat cmd[0] as the program
        (["./myapp", "--port", "8080"], ("./myapp", ["--port", "8080"])),
    ],
)
def test_go_resolve_launch_target(cmd: list[str], expected: tuple[str, list[str]] | None) -> None:
    adapter = get_adapter("go")
    assert adapter.resolve_launch_target(cmd) == expected


def test_go_panic_parse() -> None:
    adapter = get_adapter("go")
    text = (FIXTURES / "go_panic.txt").read_text(encoding="utf-8")
    parsed = adapter.parse_traceback(text)

    assert parsed.error_type == "panic"
    assert "index out of range" in parsed.message
    # Two frames in the panicking goroutine.
    assert len(parsed.frames) == 2
    # Frames stored oldest-first (matches Python convention): main.main is
    # the caller (older), main.processItems is the panic site (newer).
    assert parsed.frames[0].func == "main.main"
    assert parsed.frames[0].line == 23
    assert parsed.frames[1].func == "main.processItems"
    assert parsed.frames[1].line == 15
    # Deepest user frame is the panic site.
    assert parsed.deepest_user_frame is not None
    assert parsed.deepest_user_frame.func == "main.processItems"
    assert parsed.deepest_user_frame.line == 15


def test_go_fatal_runtime_parse_skips_runtime_frames() -> None:
    adapter = get_adapter("go")
    text = (FIXTURES / "go_fatal_runtime.txt").read_text(encoding="utf-8")
    parsed = adapter.parse_traceback(text)

    assert parsed.error_type == "fatal error"
    assert "concurrent map writes" in parsed.message

    # First (panicking) goroutine has 4 frames including runtime scaffolding.
    funcs = [f.func for f in parsed.frames]
    assert "runtime.throw" in funcs
    assert "main.writer" in funcs

    # Runtime frames must be marked non-user so the deepest-user heuristic
    # skips them and lands on real user code.
    runtime_frame = next(f for f in parsed.frames if f.func == "runtime.throw")
    assert runtime_frame.is_user_code is False
    main_frame = next(f for f in parsed.frames if f.func == "main.writer")
    assert main_frame.is_user_code is True

    # Deepest user frame should be ``main.writer`` (or ``main.main.func1``),
    # never the ``runtime.*`` scaffolding.
    assert parsed.deepest_user_frame is not None
    assert not parsed.deepest_user_frame.func.startswith("runtime.")


def test_go_method_receiver_func_names_not_truncated() -> None:
    """Pointer-receiver frames like ``(*Server).Handle`` keep their full func name.

    Regression guard: a non-greedy func regex stops at the first ``(`` inside
    ``(*Server)`` and captures a truncated ``github.com/.../server.`` name.
    """
    adapter = get_adapter("go")
    text = (FIXTURES / "go_method_panic.txt").read_text(encoding="utf-8")
    parsed = adapter.parse_traceback(text)

    assert parsed.error_type == "panic"
    funcs = [f.func for f in parsed.frames]
    assert "github.com/acme/app/server.(*Server).Handle" in funcs
    assert "github.com/acme/app/server.(*Server).ServeHTTP" in funcs
    assert "main.main" in funcs
    # No frame should have a func name truncated at the receiver's open-paren.
    assert not any(f.func.endswith(".") for f in parsed.frames)

    # Deepest user frame is the panic site — the first (innermost) method.
    assert parsed.deepest_user_frame is not None
    assert parsed.deepest_user_frame.func == "github.com/acme/app/server.(*Server).Handle"
    assert parsed.deepest_user_frame.line == 42


def test_go_parser_handles_empty_input() -> None:
    parsed = get_adapter("go").parse_traceback("")
    assert parsed.frames == []
    assert parsed.deepest_user_frame is None


def test_go_spawn_adapter_without_dlv_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``dlv`` is missing we should explain how to install it, not ENOENT."""
    adapter = get_adapter("go")
    monkeypatch.setattr("debug_agent.adapters.go.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="delve.*not on PATH"):
        adapter.spawn_adapter(12345)
