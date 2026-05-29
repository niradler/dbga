"""Adapter ABC — the language-agnostic contract for driving a DAP debugger.

A concrete adapter encapsulates everything language-specific:
  * spawning the DAP adapter as a subprocess on a TCP port
  * building the per-launch DAP payload (the ``launch`` request body)
  * parsing a crash / stack trace into structured frames
  * (optionally) spawning the debuggee in IDE-attach "listen" mode
  * (optionally) wrapping probe code for ``instrument`` defaults

The rest of the codebase (``DapSession``, ``session_proc``, the command
layer) is adapter-agnostic and pulls a concrete ``Adapter`` from the
registry in :mod:`debug_agent.adapters`.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from debug_agent.core.tracebacks import ParsedTraceback


class Adapter(ABC):
    """Language adapter interface.

    Subclasses set the class attributes and implement the abstract methods.
    They MUST be registered in :mod:`debug_agent.adapters` to be discoverable
    by ``--lang`` / extension detection.
    """

    name: ClassVar[str] = ""
    """Short language identifier — matches ``--lang`` values (``python``, ``go``, ``node``)."""

    file_extensions: ClassVar[tuple[str, ...]] = ()
    """Lower-case extensions (including leading dot) that map to this adapter."""

    interpreter_basenames: ClassVar[frozenset[str]] = frozenset()
    """Filenames that, when seen as ``cmd[0]``, indicate this language's interpreter
    (e.g. ``{"python", "python3"}`` for Python). Used by ``diagnose`` to peel
    ``<interpreter> script args...`` into the launchable ``(script, args)``."""

    # ---- adapter process -----------------------------------------------------

    @abstractmethod
    def spawn_adapter(self, port: int, *, host: str = "127.0.0.1") -> subprocess.Popen[bytes]:
        """Spawn the DAP adapter as a child subprocess, listening on ``host:port``."""

    # ---- launch payload ------------------------------------------------------

    @abstractmethod
    def launch_payload(
        self,
        *,
        script: Path,
        args: list[str] | None,
        cwd: Path | None,
        stop_on_entry: bool,
    ) -> dict[str, Any]:
        """Build the DAP ``launch`` request body for this language and target."""

    # ---- listen / IDE attach mode -------------------------------------------

    def supports_listen_mode(self) -> bool:
        """Whether ``spawn_listen_mode`` is implemented for this adapter."""
        return False

    def spawn_listen_mode(
        self,
        *,
        script: Path,
        args: list[str],
        cwd: Path,
        listen_port: int,
    ) -> subprocess.Popen[bytes]:
        """Spawn the debuggee in IDE-attach mode on ``127.0.0.1:listen_port``.

        Default implementation refuses — adapters that support attach must
        override and also return ``True`` from ``supports_listen_mode``.
        """
        raise NotImplementedError(f"{self.name!r} adapter does not support listen mode")

    def attach_url(self, host: str, port: int) -> str:
        """The scheme an IDE should use to attach. Defaults to ``<name>://host:port``."""
        return f"{self.name}://{host}:{port}"

    # ---- traceback parsing ---------------------------------------------------

    @abstractmethod
    def parse_traceback(self, text: str) -> ParsedTraceback:
        """Parse a language-specific stack trace / panic / traceback."""

    # ---- diagnose helpers ----------------------------------------------------

    def resolve_launch_target(self, cmd: list[str]) -> tuple[str, list[str]] | None:
        """Given a user command, return ``(script, script_args)`` to launch under DAP.

        Default behavior: peel a leading interpreter (e.g. ``python foo.py``)
        based on :attr:`interpreter_basenames`. Returns ``None`` when no
        launchable script can be inferred (e.g. ``python -m foo``); the
        caller should fall back to reporting the crash without a rerun.
        """
        if not cmd:
            return None
        if len(cmd) >= 2 and self._is_interpreter(cmd[0]):
            if any(flag in cmd[1:] for flag in ("-m", "-c")):
                return None
            i = 1
            while i < len(cmd) and cmd[i].startswith("-"):
                i += 1
            if i < len(cmd):
                return cmd[i], list(cmd[i + 1 :])
            return None
        return cmd[0], list(cmd[1:])

    def _is_interpreter(self, arg: str) -> bool:
        if not self.interpreter_basenames:
            return False
        base = Path(arg).name.lower()
        if base in self.interpreter_basenames:
            return True
        stripped = base.removesuffix(".exe")
        return stripped in self.interpreter_basenames

    # ---- instrumentation ----------------------------------------------------

    def probe_template(self, *, kind: str, code: str) -> str:
        """Transform a probe ``--code`` snippet before insertion. Default: passthrough.

        Concrete adapters can use this to wrap log/breakpoint/trace probes in
        language-specific syntax. Today's ``instrument`` UX requires the user
        to write the probe code explicitly, so passthrough is correct.
        """
        return code
