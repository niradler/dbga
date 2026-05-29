"""Integration test for the Go adapter — drives ``dlv dap`` end-to-end.

Skips when delve isn't on PATH so the suite stays green on machines / CI
images without a Go toolchain. To run locally:

    go install github.com/go-delve/delve/cmd/dlv@latest
    uv run pytest tests/integration/test_go_session.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from debug_agent.adapters import find_free_port, get_adapter, wait_until_listening
from debug_agent.core.dap_client import DapClient

FIXTURE = Path(__file__).parent.parent / "fixtures" / "go" / "hello.go"


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("dlv") is None,
        reason="delve (`dlv`) is not on PATH",
    ),
    pytest.mark.skipif(
        shutil.which("go") is None,
        reason="Go toolchain is not on PATH",
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


def test_go_dap_initialize_and_launch() -> None:
    """`dlv dap` accepts our `initialize` + `launch` and reports a stop."""
    adapter = get_adapter("go")
    port = find_free_port()
    proc = adapter.spawn_adapter(port)
    try:
        sock = wait_until_listening(port, timeout=60.0, proc=proc, adapter_label="go DAP adapter")
        client = DapClient()
        client.attach_socket(sock)
        try:
            caps = client.initialize()
            assert caps.get("supportsConfigurationDoneRequest") is True

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

            # ``stopOnEntry`` should yield a stopped event before the program
            # makes progress.
            stopped = client.wait_for_event("stopped", timeout=30.0)
            thread_id = int(stopped["body"]["threadId"])
            client.continue_(thread_id)
            client.wait_for_event("terminated", timeout=30.0)
        finally:
            client.disconnect()
    finally:
        _stop_adapter(proc)
