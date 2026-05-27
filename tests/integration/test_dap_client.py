"""End-to-end DAP client tests against a real debugpy adapter.

Architectural choice (mirrored in ``adapters.debugpy_adapter``): we spawn
``python -m debugpy.adapter`` as a standalone debug-server, connect to
it, and drive a normal ``initialize`` / ``launch`` handshake. The
adapter spawns the debuggee itself.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from debug_cli.adapters import debugpy_adapter
from debug_cli.core.dap_client import DapClient

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple_ok.py"


def _stop_adapter(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.mark.integration
def test_initialize_handshake() -> None:
    port = debugpy_adapter.find_free_port()
    proc = debugpy_adapter.spawn_adapter(port)
    try:
        sock = debugpy_adapter.wait_until_listening(port, timeout=10.0)
        client = DapClient()
        client.attach_socket(sock)
        try:
            caps = client.initialize()
            assert caps.get("supportsConfigurationDoneRequest") is True
        finally:
            client.disconnect()
    finally:
        _stop_adapter(proc)


@pytest.mark.integration
def test_launch_and_hit_breakpoint() -> None:
    port = debugpy_adapter.find_free_port()
    proc = debugpy_adapter.spawn_adapter(port)
    try:
        sock = debugpy_adapter.wait_until_listening(port, timeout=10.0)
        client = DapClient()
        client.attach_socket(sock)
        try:
            client.initialize()
            # Per DAP spec, `launch` does not respond until configurationDone.
            # Fire-and-forget; the `initialized` event drives configuration.
            launch_seq = client.send_request(
                "launch",
                {
                    "type": "python",
                    "request": "launch",
                    "program": str(FIXTURE.resolve()),
                    "console": "internalConsole",
                    "python": sys.executable,
                    "stopOnEntry": False,
                },
            )
            client.wait_for_event("initialized", timeout=10.0)
            client.set_breakpoints(FIXTURE.resolve(), [{"line": 3}])
            client.set_exception_breakpoints([])
            client.configuration_done()
            # Now the deferred launch response arrives.
            client.wait_response(launch_seq, "launch", timeout=10.0)
            stopped = client.wait_for_event("stopped", timeout=10.0)
            thread_id = int(stopped["body"]["threadId"])
            stack = client.stack_trace(thread_id)
            assert stack["stackFrames"][0]["line"] == 3
            client.continue_(thread_id)
            client.wait_for_event("terminated", timeout=10.0)
        finally:
            client.disconnect()
    finally:
        _stop_adapter(proc)
