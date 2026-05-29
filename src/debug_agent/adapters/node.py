"""Node.js adapter — drives vscode-js-debug's ``dapDebugServer.js``.

vscode-js-debug is the official Node DAP adapter (the one VS Code itself
uses). Its DAP server entry point is ``dapDebugServer.js``; we spawn
``node <dapDebugServer.js> <port> 127.0.0.1`` and drive a normal DAP
``initialize`` / ``launch`` handshake through it.

Resolution order for ``dapDebugServer.js`` (first match wins):
  1. ``$DBGA_JS_DEBUG_SERVER`` — explicit absolute path (CI / vendored installs).
  2. The newest ``ms-vscode.js-debug-*`` extension under VS Code / Cursor /
     VS Code Insiders' extensions directory — ``dist/src/dapDebugServer.js``.
  3. A manual install at ``~/.local/share/js-debug/src/dapDebugServer.js``
     (POSIX) or ``%LOCALAPPDATA%\\js-debug\\src\\dapDebugServer.js`` (Windows).

vscode-js-debug is **not** published to npm. The install hint surfaced by
``find_dap_server`` directs users to extract the official tarball from
https://github.com/microsoft/vscode-js-debug/releases, or to install
VS Code (which bundles it as a built-in extension).

Status: **alpha**. The handshake (``initialize``) and discovery work; the
full ``launch``-driven session does NOT yet, because vscode-js-debug
delegates execution of the launched program to a *child* DAP session via
a reverse ``startDebugging`` request — and :class:`DapClient` silently
drops server-to-client requests today (see ``_dispatch``). Promoting
this adapter to "live debugging works end-to-end" requires teaching
``DapClient`` + ``DapSession`` to handle reverse requests and spawn /
multiplex child sessions. The integration test ``test_node_dap_launch_stops``
is marked ``xfail`` and will start passing automatically once that lands.

Caveats (deliberate v1 limitations):
  * **Reverse-request support pending.** As above — the full launch flow
    is gated on that work.
  * **TypeScript is supported transparently** when ``ts-node`` / ``tsx`` is
    on PATH and the script imports register hooks — vscode-js-debug follows
    source maps automatically.
  * **Worker threads / child_process aren't followed** (same reverse-request
    blocker).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, ClassVar

from debug_agent.adapters.base import Adapter
from debug_agent.core.process import windows_no_window_flags
from debug_agent.core.tracebacks import ParsedTraceback, TracebackFrame

# ---- V8 stack-trace parser ------------------------------------------------

# Header line for unhandled errors:
#   ``Error: something broke``
#   ``TypeError: Cannot read properties of undefined (reading 'foo')``
#   ``ReferenceError: x is not defined``
_ERROR_HEADER_RE = re.compile(
    r"^\s*(?P<type>[A-Z]\w*(?:Error|Exception|Warning))(?::\s*(?P<msg>.*))?$"
)

# V8 stack frame, full form: ``    at fnName (/path/file.js:line:col)``
_FRAME_NAMED_RE = re.compile(
    r"^\s*at\s+(?P<func>.+?)\s+\((?P<file>.+?):(?P<line>\d+):(?P<col>\d+)\)\s*$"
)

# V8 stack frame, anonymous: ``    at /path/file.js:line:col``
_FRAME_ANON_RE = re.compile(r"^\s*at\s+(?P<file>.+?):(?P<line>\d+):(?P<col>\d+)\s*$")

# Frames whose file path contains one of these markers are non-user code.
_LIB_MARKERS = ("node_modules", "node:internal/", "internal/process/")


def _is_library_path(path: str) -> bool:
    if path.startswith("node:"):
        return True
    return any(marker in path for marker in _LIB_MARKERS)


def _parse_node_traceback(text: str) -> ParsedTraceback:
    parsed = ParsedTraceback(raw=text)
    lines = text.splitlines()

    frames: list[TracebackFrame] = []
    for line in lines:
        # Header — first ``Error: ...`` style line wins.
        if not parsed.error_type:
            m_err = _ERROR_HEADER_RE.match(line)
            if m_err:
                parsed.error_type = m_err.group("type")
                parsed.message = (m_err.group("msg") or "").strip()
                continue

        m = _FRAME_NAMED_RE.match(line)
        if m:
            frames.append(
                TracebackFrame(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    func=m.group("func"),
                    code="",
                    is_user_code=not _is_library_path(m.group("file")),
                )
            )
            continue
        m_anon = _FRAME_ANON_RE.match(line)
        if m_anon:
            frames.append(
                TracebackFrame(
                    file=m_anon.group("file"),
                    line=int(m_anon.group("line")),
                    func="<anonymous>",
                    code="",
                    is_user_code=not _is_library_path(m_anon.group("file")),
                )
            )

    # V8 prints stack newest-first (failure site at the top). Flip to
    # oldest-first so the shared ``deepest_user_frame`` heuristic — which
    # walks frames in reverse — lands on the failure site.
    frames.reverse()
    parsed.frames = frames

    for frame in reversed(frames):
        if frame.is_user_code:
            parsed.deepest_user_frame = frame
            break
    if parsed.deepest_user_frame is None and frames:
        parsed.deepest_user_frame = frames[-1]

    return parsed


# ---- vscode-js-debug location -------------------------------------------

# Inside an installed VS Code extension: ``dist/src/dapDebugServer.js``.
_EXTENSION_DAP_REL = Path("dist") / "src" / "dapDebugServer.js"

# Inside a manual GitHub-release extraction: ``src/dapDebugServer.js``.
_MANUAL_DAP_REL = Path("src") / "dapDebugServer.js"

_INSTALL_HINT = (
    "vscode-js-debug is not installed. Either: (a) install VS Code (it ships "
    "vscode-js-debug as a built-in extension); (b) extract the latest "
    "`js-debug-dap-vX.Y.Z.tar.gz` from "
    "https://github.com/microsoft/vscode-js-debug/releases into "
    "~/.local/share/ (POSIX) or %LOCALAPPDATA% (Windows); or (c) set "
    "$DBGA_JS_DEBUG_SERVER to an explicit dapDebugServer.js path."
)


def _vscode_extension_roots() -> list[Path]:
    """Per-user extension directories for VS Code / Cursor / Insiders."""
    home = Path.home()
    candidates = [
        home / ".vscode" / "extensions",
        home / ".vscode-insiders" / "extensions",
        home / ".vscode-server" / "extensions",  # remote-SSH host
        home / ".cursor" / "extensions",
        home / ".windsurf" / "extensions",
    ]
    return [c for c in candidates if c.is_dir()]


def _latest_js_debug_extension(extensions_dir: Path) -> Path | None:
    """Pick the newest ``ms-vscode.js-debug-*`` extension directory under root."""
    candidates = [p for p in extensions_dir.glob("ms-vscode.js-debug*") if p.is_dir()]
    if not candidates:
        return None
    # Sort by directory name (which embeds the version) so the newest wins.
    candidates.sort(key=lambda p: p.name)
    return candidates[-1]


def _manual_install_roots() -> list[Path]:
    """Common locations a user might extract the GitHub-release tarball to."""
    home = Path.home()
    roots = [
        home / ".local" / "share" / "js-debug",
        home / "js-debug",
    ]
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            roots.append(Path(local_appdata) / "js-debug")
    return roots


def find_dap_server() -> Path:
    """Locate ``dapDebugServer.js`` or raise ``RuntimeError`` with install hint."""
    explicit = os.environ.get("DBGA_JS_DEBUG_SERVER")
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise RuntimeError(
            f"$DBGA_JS_DEBUG_SERVER points at {explicit!r} but that file does not exist."
        )

    # VS Code / Cursor / Insiders extension installs.
    for ext_root in _vscode_extension_roots():
        ext = _latest_js_debug_extension(ext_root)
        if ext is not None:
            candidate = ext / _EXTENSION_DAP_REL
            if candidate.is_file():
                return candidate

    # Manual tarball extractions.
    for root in _manual_install_roots():
        candidate = root / _MANUAL_DAP_REL
        if candidate.is_file():
            return candidate

    raise RuntimeError(_INSTALL_HINT)


# ---- adapter ---------------------------------------------------------------


class NodeAdapter(Adapter):
    name: ClassVar[str] = "node"
    file_extensions: ClassVar[tuple[str, ...]] = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")
    interpreter_basenames: ClassVar[frozenset[str]] = frozenset(
        {"node", "ts-node", "tsx", "node.exe", "ts-node.exe", "tsx.exe"}
    )

    def _find_node(self) -> str:
        node = shutil.which("node")
        if node is None:
            raise RuntimeError(
                "node is not on PATH. Install Node.js from https://nodejs.org/ "
                "and ensure `node` resolves on PATH."
            )
        return node

    # ---- adapter process -----------------------------------------------

    def spawn_adapter(self, port: int, *, host: str = "127.0.0.1") -> subprocess.Popen[bytes]:
        """Spawn ``node dapDebugServer.js <port> <host>`` as the DAP server."""
        node = self._find_node()
        dap_server = find_dap_server()
        kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = windows_no_window_flags()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(  # type: ignore[call-overload,no-any-return]
            [node, str(dap_server), str(port), host],
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
        # vscode-js-debug uses the ``pwa-node`` (Preview Wildcat-Analytics, the
        # internal "v2" debugger) type identifier. ``skipFiles`` keeps the
        # stop-on-entry from landing in Node's own internal bootstrap files.
        payload: dict[str, Any] = {
            "type": "pwa-node",
            "request": "launch",
            "program": str(Path(script).resolve()),
            "stopOnEntry": stop_on_entry,
            "console": "internalConsole",
            "skipFiles": ["<node_internals>/**"],
        }
        if args is not None:
            payload["args"] = args
        if cwd is not None:
            payload["cwd"] = str(cwd)
        return payload

    # ---- listen / IDE attach mode ---------------------------------------

    def supports_listen_mode(self) -> bool:
        """vscode-js-debug's dapDebugServer.js IS the listen-mode server."""
        return True

    def spawn_listen_mode(
        self,
        *,
        script: Path,
        args: list[str],
        cwd: Path,
        listen_port: int,
    ) -> subprocess.Popen[bytes]:
        # Like the Go adapter: ``dapDebugServer.js`` accepts a DAP launch
        # request after it starts, so the IDE's own launch config drives
        # program/args. We use ``script`` / ``args`` only for meta.json.
        del script, args  # IDE-side launch config takes over
        node = self._find_node()
        dap_server = find_dap_server()
        cmd = [node, str(dap_server), str(listen_port), "127.0.0.1"]
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
        return f"js-debug://{host}:{port}"

    # ---- traceback parsing ----------------------------------------------

    def parse_traceback(self, text: str) -> ParsedTraceback:
        return _parse_node_traceback(text)

    # ---- diagnose helpers -----------------------------------------------

    def resolve_launch_target(self, cmd: list[str]) -> tuple[str, list[str]] | None:
        """Peel ``node [-flags] script.js args`` / ``ts-node script.ts args``.

        Handles common Node CLI flags including the ``-r module`` / ``--require module``
        pair, which consumes the next argv slot as its module name.
        """
        if not cmd:
            return None
        if len(cmd) >= 2 and self._is_interpreter(cmd[0]):
            i = 1
            while i < len(cmd) and cmd[i].startswith("-"):
                # ``-r <mod>`` / ``--require <mod>`` consume the next slot too.
                if cmd[i] in ("-r", "--require") and i + 1 < len(cmd):
                    i += 2
                    continue
                # Args of the form ``--flag=value`` are self-contained.
                i += 1
            if i < len(cmd):
                return cmd[i], list(cmd[i + 1 :])
            return None
        return super().resolve_launch_target(cmd)
