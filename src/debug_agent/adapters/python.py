"""Python adapter — drives ``debugpy.adapter`` as our DAP server.

Architectural note (kept from the original ``debugpy_adapter`` module): we
use the **standalone adapter** pattern. We spawn ``python -m debugpy.adapter
--host 127.0.0.1 --port <port>`` as its own subprocess, then drive a normal
``initialize`` / ``launch`` sequence through it. The adapter spawns the
debuggee as its own child.

We tried the simpler single-step pattern (``python -m debugpy --listen
:<port> --wait-for-client <script>``) first, but in debugpy 1.8.20 that mode
delegates to an internal adapter that never gets spawned in our environment
— it hangs forever on ``Waiting for adapter endpoints...``. The standalone
adapter pattern is reliable and well documented; don't switch back.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

from debug_agent.adapters.base import Adapter
from debug_agent.core.process import windows_no_window_flags
from debug_agent.core.tracebacks import ParsedTraceback
from debug_agent.core.tracebacks import parse_traceback as _parse_python_traceback


class PythonAdapter(Adapter):
    name: ClassVar[str] = "python"
    file_extensions: ClassVar[tuple[str, ...]] = (".py",)
    interpreter_basenames: ClassVar[frozenset[str]] = frozenset(
        {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}
    )

    # ---- adapter process -----------------------------------------------------

    def spawn_adapter(self, port: int, *, host: str = "127.0.0.1") -> subprocess.Popen[bytes]:
        """Spawn ``debugpy.adapter`` in debugServer mode on ``host:port``.

        The adapter spawns the debuggee as its own child. On POSIX we put the
        adapter in its own session so ``killpg`` takes down the debuggee with
        it. On Windows we rely on the parent/child relationship and
        ``taskkill /F /T`` to walk descendants — we deliberately do *not* set
        ``CREATE_NEW_PROCESS_GROUP``; that flag changes signal-handler defaults
        in the child and triggers a thread-init race inside the debugpy
        adapter under heavy concurrent launches.
        """
        kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = windows_no_window_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(  # type: ignore[call-overload,no-any-return]
            [sys.executable, "-m", "debugpy.adapter", "--host", host, "--port", str(port)],
            **kwargs,
        )

    # ---- launch payload ------------------------------------------------------

    def launch_payload(
        self,
        *,
        script: Path,
        args: list[str] | None,
        cwd: Path | None,
        stop_on_entry: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "python",
            "request": "launch",
            "program": str(Path(script).resolve()),
            "console": "internalConsole",
            "python": sys.executable,
            "stopOnEntry": stop_on_entry,
        }
        if args is not None:
            payload["args"] = args
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return payload

    # ---- listen / IDE attach mode -------------------------------------------

    def supports_listen_mode(self) -> bool:
        return True

    def spawn_listen_mode(
        self,
        *,
        script: Path,
        args: list[str],
        cwd: Path,
        listen_port: int,
    ) -> subprocess.Popen[bytes]:
        """Spawn ``python -m debugpy --listen --wait-for-client <script>``.

        debugpy in this mode accepts a single client connection — giving it
        to VS Code (rather than our own DAP client) is the entire purpose.
        """
        cmd = [
            sys.executable,
            "-m",
            "debugpy",
            "--listen",
            f"127.0.0.1:{listen_port}",
            "--wait-for-client",
            str(script),
            *args,
        ]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(cwd),
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = windows_no_window_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(cmd, **kwargs)

    def attach_url(self, host: str, port: int) -> str:
        return f"debugpy://{host}:{port}"

    # ---- traceback parsing ---------------------------------------------------

    def parse_traceback(self, text: str) -> ParsedTraceback:
        return _parse_python_traceback(text)
