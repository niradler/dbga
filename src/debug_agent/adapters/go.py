"""Go adapter — drives ``dlv dap`` (delve) as our DAP server.

`dlv dap` is a turn-key DAP server: ``dlv dap --listen=127.0.0.1:<port>``
accepts a single DAP client (us) and runs the program described in the
``launch`` request. We use ``mode: "debug"`` so delve compiles + runs the
program in one step; ``mode: "exec"`` would require the user to pre-build.

We require delve to be on PATH. If it isn't, ``spawn_adapter`` surfaces a
clear "delve not installed" error instead of a cryptic ENOENT.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

from debug_agent.adapters.base import Adapter
from debug_agent.core.process import windows_no_window_flags
from debug_agent.core.tracebacks import ParsedTraceback, TracebackFrame

# ---- panic / fatal-error parser -------------------------------------------

# ``goroutine 1 [running]:`` / ``goroutine 5 [select, 2 minutes]:``
_GOROUTINE_RE = re.compile(r"^goroutine\s+(\d+)\s+\[([^\]]+)\]:\s*$")

# The function-call header inside a goroutine dump:
#   ``main.processItems({0xc000018180, 0x3, 0x3})``
#   ``github.com/x/y/pkg.(*Server).Handle(0xc0000180c0)``   ← method receiver
#   ``runtime.gopanic(0x10b0e80, 0xc0000180c0)``
#   ``main.Map[...](0x...)``                                  ← generic
#   ``main.main.func1()``                                    ← closure
# The func name is the non-space token *before the final argument-parens*.
# A greedy ``\S+`` backtracks to the LAST ``(`` so embedded parens in a
# pointer-receiver name like ``(*Server)`` stay part of the func — a
# non-greedy match would wrongly stop at that first inner ``(``.
_FUNC_RE = re.compile(r"^(?P<func>\S+)\((?P<args>.*)\)\s*$")

# The source-location line that follows a function header:
#   ``\t/abs/path/main.go:15 +0x9e``
#   ``\t/path/runtime/panic.go:1047 +0x5d fp=0xc... sp=0xc... pc=0x...``
# Optional trailing annotations (``+0xN``, ``fp=...``, etc.) are tolerated.
_LOC_RE = re.compile(r"^\s+(?P<file>.+?):(?P<line>\d+)(?:\s+\S.*)?$")

# ``panic: <message>`` or ``fatal error: <message>``
_PANIC_RE = re.compile(r"^(?P<type>panic|fatal error):\s*(?P<msg>.*)$")

# Frames whose function name starts with one of these prefixes are runtime
# scaffolding, not user code — we mark them ``is_user_code=False`` so the
# deepest-user-frame heuristic skips them.
_RUNTIME_PREFIXES = ("runtime.", "sync.", "reflect.", "internal/")


def _is_runtime_frame(func: str) -> bool:
    return any(func.startswith(p) for p in _RUNTIME_PREFIXES)


def _parse_go_traceback(text: str) -> ParsedTraceback:
    parsed = ParsedTraceback(raw=text)
    lines = text.splitlines()

    # ---- header: first ``panic:`` / ``fatal error:`` we see ----------------
    for line in lines:
        m = _PANIC_RE.match(line.strip())
        if m:
            parsed.error_type = m.group("type")
            parsed.message = m.group("msg").strip()
            break

    # ---- frames: walk goroutines, take the first (panic) goroutine --------
    # delve / the Go runtime print the panicking goroutine first. Subsequent
    # goroutines are bystanders and don't matter for "where did this crash."
    frames: list[TracebackFrame] = []
    in_goroutine = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if _GOROUTINE_RE.match(line):
            if in_goroutine:
                # Second goroutine block — stop; first one is the panic site.
                break
            in_goroutine = True
            i += 1
            continue
        if not in_goroutine:
            i += 1
            continue
        func_m = _FUNC_RE.match(line)
        if func_m and i + 1 < len(lines):
            loc_m = _LOC_RE.match(lines[i + 1])
            if loc_m:
                frames.append(
                    TracebackFrame(
                        file=loc_m.group("file"),
                        line=int(loc_m.group("line")),
                        func=func_m.group("func"),
                        code="",
                        is_user_code=not _is_runtime_frame(func_m.group("func")),
                    )
                )
                i += 2
                continue
        i += 1

    # Go prints the call stack newest-first (panic site at the top). The rest
    # of the codebase expects oldest-first (matching Python tracebacks: the
    # last frame is the failure site, which ``_find_deepest_user_frame``
    # walks in reverse). Flip so ``frames[-1]`` is the panic site.
    frames.reverse()
    parsed.frames = frames

    # Deepest user frame = last user-code frame from the end.
    for frame in reversed(frames):
        if frame.is_user_code:
            parsed.deepest_user_frame = frame
            break
    if parsed.deepest_user_frame is None and frames:
        parsed.deepest_user_frame = frames[-1]

    return parsed


# ---- adapter --------------------------------------------------------------


class GoAdapter(Adapter):
    name: ClassVar[str] = "go"
    file_extensions: ClassVar[tuple[str, ...]] = (".go",)
    interpreter_basenames: ClassVar[frozenset[str]] = frozenset({"go"})

    def _find_dlv(self) -> str:
        """Locate ``dlv`` on PATH. Raises ``RuntimeError`` with install hint."""
        dlv = shutil.which("dlv")
        if dlv is None:
            raise RuntimeError(
                "delve (`dlv`) is not on PATH. Install it with "
                "`go install github.com/go-delve/delve/cmd/dlv@latest` "
                "and ensure $GOPATH/bin (or $HOME/go/bin) is on PATH."
            )
        return dlv

    # ---- adapter process -------------------------------------------------

    def spawn_adapter(self, port: int, *, host: str = "127.0.0.1") -> subprocess.Popen[bytes]:
        """Spawn ``dlv dap --listen=host:port`` as the DAP server."""
        dlv = self._find_dlv()
        kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = windows_no_window_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(  # type: ignore[call-overload,no-any-return]
            [dlv, "dap", f"--listen={host}:{port}"],
            **kwargs,
        )

    # ---- launch payload --------------------------------------------------

    def launch_payload(
        self,
        *,
        script: Path,
        args: list[str] | None,
        cwd: Path | None,
        stop_on_entry: bool,
    ) -> dict[str, Any]:
        # ``mode: "debug"`` makes delve compile + run the program in one step.
        # ``program`` can be a .go file or a package directory; we hand it a
        # resolved absolute path so delve's cwd resolution stays predictable.
        resolved_program = Path(script).resolve()
        payload: dict[str, Any] = {
            "type": "go",
            "request": "launch",
            "mode": "debug",
            "program": str(resolved_program),
            "stopOnEntry": stop_on_entry,
        }
        if args is not None:
            payload["args"] = args
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return payload

    # ---- listen / IDE attach mode ---------------------------------------

    def supports_listen_mode(self) -> bool:
        """``dlv dap`` IS the listen-mode server — the IDE just connects to it.

        In our daemon path we *also* connect to the same kind of server with
        our own client. For ``--listen`` (IDE-attach), we spawn the same
        process but don't attach a client; the IDE will. The IDE-side launch
        config controls program/args, not us.
        """
        return True

    def spawn_listen_mode(
        self,
        *,
        script: Path,
        args: list[str],
        cwd: Path,
        listen_port: int,
    ) -> subprocess.Popen[bytes]:
        # NOTE: delve doesn't ship a separate "listen + wait" mode for DAP —
        # ``dlv dap --listen`` is itself the attachable server. The IDE
        # configures program/args on its end via the DAP ``launch`` request,
        # so ``script`` / ``args`` here are only used for ``meta.json``
        # bookkeeping and not passed to delve.
        del script, args  # unused; see note above
        dlv = self._find_dlv()
        cmd = [dlv, "dap", f"--listen=127.0.0.1:{listen_port}"]
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
        return f"dlv-dap://{host}:{port}"

    # ---- traceback parsing ----------------------------------------------

    def parse_traceback(self, text: str) -> ParsedTraceback:
        return _parse_go_traceback(text)

    # ---- diagnose helpers -----------------------------------------------

    def resolve_launch_target(self, cmd: list[str]) -> tuple[str, list[str]] | None:
        """Peel a ``go run <main.go> args...`` invocation.

        Falls back to the default Adapter behavior (treat ``cmd[0]`` as the
        program) for anything that doesn't match ``go run`` — e.g. someone
        invoking a pre-built binary directly.
        """
        if len(cmd) >= 3 and self._is_interpreter(cmd[0]) and cmd[1] == "run":
            # Strip ``go run``; the first non-flag arg is the program.
            i = 2
            while i < len(cmd) and cmd[i].startswith("-"):
                i += 1
            if i < len(cmd):
                return cmd[i], list(cmd[i + 1 :])
            return None
        # ``go test`` would need mode:"test"; out of scope for v1.
        if len(cmd) >= 2 and self._is_interpreter(cmd[0]) and cmd[1] == "test":
            return None
        return super().resolve_launch_target(cmd)
