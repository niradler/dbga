"""Unit tests for bounded adapter-startup retry.

The debugpy adapter has a known startup race on Windows: its
``accept_worker`` thread can crash on init under back-to-back launches,
so the adapter exits (code 0) before it ever listens, and
``wait_until_listening`` raises ``RuntimeError`` ("exited before
listening"). One transient crash shouldn't fail the whole session —
``open_adapter_connection`` respawns on a fresh port a bounded number of
times. These tests drive that orchestration through a clean seam (a fake
adapter + monkeypatched socket helpers) — no real debugpy spawn.
"""

from __future__ import annotations

from typing import Any

import pytest

from debug_agent.core import dap_session


class _FakeProc:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class _FakeAdapter:
    name = "fake"

    def __init__(self) -> None:
        self.spawns = 0

    def spawn_adapter(self, port: int, *, host: str = "127.0.0.1") -> Any:
        self.spawns += 1
        return _FakeProc(pid=1000 + self.spawns)


def test_open_adapter_connection_retries_past_a_startup_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single 'exited before listening' crash is retried, then succeeds."""
    adapter = _FakeAdapter()
    killed: list[int] = []
    sentinel_sock = object()
    calls = {"n": 0}

    monkeypatch.setattr(dap_session, "find_free_port", lambda: 5000 + calls["n"])
    monkeypatch.setattr(dap_session, "kill_tree", lambda pid: killed.append(pid))

    def fake_wait(port: int, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("fake DAP adapter exited with code 0 before listening")
        return sentinel_sock

    monkeypatch.setattr(dap_session, "wait_until_listening", fake_wait)

    proc, sock, port = dap_session.open_adapter_connection(adapter, timeout=1.0, attempts=3)

    assert sock is sentinel_sock
    assert adapter.spawns == 2  # respawned once after the crash
    assert killed == [1001]  # the dead first adapter was tree-killed


def test_open_adapter_connection_raises_after_exhausting_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every attempt crashes, the last error propagates (no infinite loop)."""
    adapter = _FakeAdapter()
    monkeypatch.setattr(dap_session, "find_free_port", lambda: 6000)
    monkeypatch.setattr(dap_session, "kill_tree", lambda pid: None)

    def always_crash(port: int, **kwargs: Any) -> Any:
        raise RuntimeError("exited before listening")

    monkeypatch.setattr(dap_session, "wait_until_listening", always_crash)

    with pytest.raises(RuntimeError, match="exited before listening"):
        dap_session.open_adapter_connection(adapter, timeout=1.0, attempts=3)
    assert adapter.spawns == 3  # tried exactly `attempts` times


def test_open_adapter_connection_succeeds_first_try_no_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: one spawn, one wait, no respawn, no kill."""
    adapter = _FakeAdapter()
    killed: list[int] = []
    sentinel_sock = object()
    monkeypatch.setattr(dap_session, "find_free_port", lambda: 7000)
    monkeypatch.setattr(dap_session, "kill_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(dap_session, "wait_until_listening", lambda port, **kw: sentinel_sock)

    proc, sock, port = dap_session.open_adapter_connection(adapter, timeout=1.0, attempts=3)
    assert sock is sentinel_sock
    assert adapter.spawns == 1
    assert killed == []
