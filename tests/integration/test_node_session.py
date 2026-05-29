"""Integration test for the Node adapter — drives vscode-js-debug.

Two test surfaces:

  * ``test_node_dap_initialize`` — verifies the handshake and that our
    discovery logic finds ``dapDebugServer.js``. Always expected to pass
    when js-debug is installed.

  * ``test_node_dap_launch_stops`` — the full launch / stop / continue
    flow. **Currently xfail** because vscode-js-debug delegates the actual
    program execution to a *child* DAP session via a reverse
    ``startDebugging`` request, and our ``DapClient`` doesn't yet handle
    server-to-client requests (it silently drops them — see
    ``dap_client.py::_dispatch``). The child session is never created, so
    no ``stopped`` event ever reaches us. Promoting this test to pass
    requires reverse-request + child-session support — see follow-up issue.

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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "vscode-js-debug delegates `launch` to a child session via reverse "
        "`startDebugging` requests; DapClient doesn't handle reverse requests "
        "yet, so the child is never created and `stopped` never arrives. "
        "Tracked as follow-up work — see NodeAdapter docstring."
    ),
)
def test_node_dap_launch_stops() -> None:
    """Full launch -> stopOnEntry -> continue -> terminated flow.

    Will start passing automatically once DapClient learns to handle
    server-to-client requests (specifically vscode-js-debug's
    `startDebugging` reverse-request and the resulting child session).
    """
    adapter = get_adapter("node")
    port = find_free_port()
    proc = adapter.spawn_adapter(port)
    try:
        sock = wait_until_listening(port, timeout=60.0, proc=proc, adapter_label="node DAP adapter")
        client = DapClient()
        client.attach_socket(sock)
        try:
            client.initialize()
            launch_seq = client.send_request(
                "launch",
                adapter.launch_payload(
                    script=FIXTURE,
                    args=None,
                    cwd=FIXTURE.parent,
                    stop_on_entry=True,
                ),
            )
            client.wait_for_event("initialized", timeout=60.0)
            client.set_exception_breakpoints([])
            client.configuration_done()
            client.wait_response(launch_seq, "launch", timeout=60.0)

            stopped = client.wait_for_event("stopped", timeout=30.0)
            thread_id = int(stopped["body"]["threadId"])
            client.continue_(thread_id)
            client.wait_for_event("terminated", timeout=30.0)
        finally:
            client.disconnect()
    finally:
        _stop_adapter(proc)
