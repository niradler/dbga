"""Integration test for the Node adapter — drives vscode-js-debug end-to-end.

Two test surfaces:

  * ``test_node_dap_initialize`` — verifies the handshake and that our
    discovery logic finds ``dapDebugServer.js``.

  * ``test_node_dap_launch_stops`` — the full launch / stop / continue
    flow. Exercises ``DapClient``'s reverse-request handling plus
    ``DapSession``'s child-session orchestration — vscode-js-debug
    delegates every launched program to a child DAP session via a
    ``startDebugging`` reverse-request, which our client/session pair
    handles transparently.

Skips when ``node`` isn't on PATH OR vscode-js-debug can't be discovered.
Discovery looks at ``$DBGA_JS_DEBUG_SERVER``, VS Code / Cursor / Insiders
extension dirs, and ``~/.local/share/js-debug``. To install manually:

    # POSIX
    curl -L -o /tmp/js-debug.tar.gz \\
      https://github.com/microsoft/vscode-js-debug/releases/latest/download/js-debug-dap-vLATEST.tar.gz
    mkdir -p ~/.local/share && tar -xzf /tmp/js-debug.tar.gz -C ~/.local/share/

    # then
    uv run pytest tests/integration/test_node_session.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from debug_agent.adapters import find_free_port, get_adapter, wait_until_listening
from debug_agent.adapters.node import find_dap_server
from debug_agent.core.dap_client import DapClient
from debug_agent.core.dap_session import DapSession

FIXTURE = Path(__file__).parent.parent / "fixtures" / "node" / "hello.js"


def _js_debug_available() -> bool:
    try:
        find_dap_server()
        return True
    except RuntimeError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH"),
    pytest.mark.skipif(
        not _js_debug_available(),
        reason="vscode-js-debug not installed (see module docstring)",
    ),
]


def _stop_adapter(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_node_dap_initialize() -> None:
    """`dapDebugServer.js` accepts our `initialize` handshake."""
    adapter = get_adapter("node")
    port = find_free_port()
    proc = adapter.spawn_adapter(port)
    try:
        sock = wait_until_listening(port, timeout=60.0, proc=proc, adapter_label="node DAP adapter")
        client = DapClient()
        client.attach_socket(sock)
        try:
            caps = client.initialize()
            assert caps.get("supportsConfigurationDoneRequest") is True
        finally:
            client.disconnect()
    finally:
        _stop_adapter(proc)


def test_node_dap_launch_stops() -> None:
    """Full launch → stopOnEntry → continue → terminated flow via DapSession.

    Goes through ``DapSession`` (not raw ``DapClient``) so the
    ``startDebugging`` reverse-handler is wired — vscode-js-debug delegates
    every launched program to a child DAP session, which our session
    machinery now opens and tracks automatically.
    """
    adapter = get_adapter("node")
    session = DapSession(session_id="node-launch-test", adapter=adapter)
    try:
        session.start(
            script=FIXTURE,
            args=[],
            cwd=FIXTURE.parent,
            stop_on_entry=True,
        )
        ctx = session.wait_for_stop(timeout=30.0)
        # stopOnEntry should land us paused before the program executes.
        assert ctx.status == "stopped", f"expected stopped, got {ctx.status!r} ({ctx.reason!r})"
        assert ctx.session_id == "node-launch-test"

        final = session.continue_(timeout=30.0)
        # The program is two-statement; it should terminate before we step.
        assert final.status in {"terminated", "exited"}, (
            f"expected terminated, got {final.status!r}"
        )
    finally:
        session.release()
