"""Unit tests for the Node adapter (registry + V8 stack parser + launch payload).

Integration-level tests that actually spawn vscode-js-debug's
``dapDebugServer.js`` live in ``tests/integration/test_node_session.py``
and skip when js-debug isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from debug_agent.adapters import detect_language, get_adapter, list_adapters
from debug_agent.adapters.node import NodeAdapter, _parse_node_traceback

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tracebacks"


def test_node_adapter_registered() -> None:
    assert "node" in list_adapters()
    adapter = get_adapter("node")
    assert isinstance(adapter, NodeAdapter)
    assert adapter.name == "node"


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("app.js", "node"),
        ("src/main.mjs", "node"),
        ("dist/bundle.cjs", "node"),
        ("server.ts", "node"),
        ("types.d.ts", "node"),  # treated as node (no separate `dts` lang)
        ("main.tsx", None),  # tsx files aren't claimed (frontend bundler territory)
    ],
)
def test_node_extension_detection(script: str, expected: str | None) -> None:
    assert detect_language(script) == expected


def test_node_launch_payload_shape() -> None:
    adapter = get_adapter("node")
    payload = adapter.launch_payload(
        script=Path("app.js"),
        args=["--port", "3000"],
        cwd=Path("/srv/app"),
        stop_on_entry=True,
    )
    assert payload["type"] == "pwa-node"
    assert payload["request"] == "launch"
    assert payload["stopOnEntry"] is True
    assert payload["args"] == ["--port", "3000"]
    assert payload["program"].endswith("app.js")
    # ``skipFiles`` keeps stopOnEntry from landing in Node's internal bootstrap.
    assert "<node_internals>/**" in payload["skipFiles"]


def test_node_attach_url_uses_js_debug_scheme() -> None:
    adapter = get_adapter("node")
    assert adapter.attach_url("127.0.0.1", 9229) == "js-debug://127.0.0.1:9229"


def test_node_supports_listen_mode() -> None:
    assert get_adapter("node").supports_listen_mode() is True


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        # Plain ``node script.js args``
        (["node", "app.js"], ("app.js", [])),
        (["node", "app.js", "--port", "3000"], ("app.js", ["--port", "3000"])),
        # Self-contained flags
        (["node", "--inspect", "app.js", "x"], ("app.js", ["x"])),
        # ``-r module`` consumes the next slot
        (["node", "-r", "ts-node/register", "src/main.ts", "x"], ("src/main.ts", ["x"])),
        (
            ["node", "--require", "dotenv/config", "app.js", "y"],
            ("app.js", ["y"]),
        ),
        # ts-node / tsx invocations
        (["ts-node", "src/main.ts"], ("src/main.ts", [])),
        (["tsx", "src/main.ts", "--watch"], ("src/main.ts", ["--watch"])),
        # Pre-built CLI: treat cmd[0] as the program
        (["./bin/server", "--port", "3000"], ("./bin/server", ["--port", "3000"])),
    ],
)
def test_node_resolve_launch_target(cmd: list[str], expected: tuple[str, list[str]] | None) -> None:
    adapter = get_adapter("node")
    assert adapter.resolve_launch_target(cmd) == expected


def test_node_typeerror_parse() -> None:
    text = (FIXTURES / "node_typeerror.txt").read_text(encoding="utf-8")
    parsed = _parse_node_traceback(text)
    assert parsed.error_type == "TypeError"
    assert "undefined" in parsed.message

    user_frames = [f for f in parsed.frames if f.is_user_code]
    library_frames = [f for f in parsed.frames if not f.is_user_code]

    # Both user frames (main.js calls) are present, marked as user code.
    assert any(f.func == "processItems" for f in user_frames)
    assert any(f.func == "main" for f in user_frames)

    # ``node:internal/...`` frames must be marked non-user.
    assert library_frames, "expected node:internal frames to be marked as library code"
    assert all(
        "node:internal" in f.file or "internal/" in f.file or "node_modules" in f.file
        for f in library_frames
    )

    # Deepest user frame is the failure site (processItems, line 15).
    assert parsed.deepest_user_frame is not None
    assert parsed.deepest_user_frame.func == "processItems"
    assert parsed.deepest_user_frame.line == 15


def test_node_referenceerror_parse_handles_anonymous_and_node_modules() -> None:
    text = (FIXTURES / "node_referenceerror.txt").read_text(encoding="utf-8")
    parsed = _parse_node_traceback(text)
    assert parsed.error_type == "ReferenceError"

    # Anonymous frame (``at /path/app.js:8:3``) parses with func='<anonymous>'.
    anon = next((f for f in parsed.frames if "/app.js" in f.file), None)
    assert anon is not None
    assert anon.func == "<anonymous>"
    assert anon.line == 8
    assert anon.is_user_code is True

    # node_modules + node:internal frames marked non-user.
    library_files = [f.file for f in parsed.frames if not f.is_user_code]
    assert any("node_modules" in p for p in library_files)
    assert any("node:internal" in p or "internal/" in p for p in library_files)

    # Deepest user frame should be the anonymous app.js:8 frame.
    assert parsed.deepest_user_frame is not None
    assert "/app.js" in parsed.deepest_user_frame.file


def test_node_parser_handles_empty_input() -> None:
    parsed = _parse_node_traceback("")
    assert parsed.frames == []
    assert parsed.deepest_user_frame is None


def test_node_spawn_adapter_without_node_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``node`` is missing we should point at nodejs.org, not ENOENT."""
    adapter = get_adapter("node")
    monkeypatch.setattr("debug_agent.adapters.node.shutil.which", lambda _: None)
    with pytest.raises(RuntimeError, match="node is not on PATH"):
        adapter.spawn_adapter(12345)


def test_find_dap_server_uses_explicit_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`$DBGA_JS_DEBUG_SERVER` overrides every auto-discovery path."""
    from debug_agent.adapters.node import find_dap_server

    fake = tmp_path / "dapDebugServer.js"
    fake.write_text("// fake")
    monkeypatch.setenv("DBGA_JS_DEBUG_SERVER", str(fake))
    assert find_dap_server() == fake


def test_find_dap_server_errors_when_env_var_points_at_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from debug_agent.adapters.node import find_dap_server

    monkeypatch.setenv("DBGA_JS_DEBUG_SERVER", str(tmp_path / "missing.js"))
    with pytest.raises(RuntimeError, match="does not exist"):
        find_dap_server()


def test_latest_js_debug_extension_picks_highest_numeric_version(tmp_path: Path) -> None:
    """1.10.0 must beat 1.9.0 — a plain string sort gets this wrong."""
    from debug_agent.adapters.node import _latest_js_debug_extension

    for ver in ("1.9.0", "1.10.0", "1.2.0"):
        (tmp_path / f"ms-vscode.js-debug-{ver}").mkdir()
    # An unrelated extension must be ignored.
    (tmp_path / "ms-python.python-2024.1.0").mkdir()

    latest = _latest_js_debug_extension(tmp_path)
    assert latest is not None
    assert latest.name == "ms-vscode.js-debug-1.10.0"


def test_latest_js_debug_extension_none_when_absent(tmp_path: Path) -> None:
    from debug_agent.adapters.node import _latest_js_debug_extension

    (tmp_path / "ms-python.python-2024.1.0").mkdir()
    assert _latest_js_debug_extension(tmp_path) is None
