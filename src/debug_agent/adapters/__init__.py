"""Language-adapter registry + detection.

To add a new language: implement :class:`debug_agent.adapters.base.Adapter`
in a new submodule and register the class in ``_REGISTRY`` below. Detection
(``--lang`` flag, script-extension match) flows through the helpers here.
"""

from __future__ import annotations

from pathlib import Path

from debug_agent.adapters._socket import find_free_port, wait_until_listening
from debug_agent.adapters.base import Adapter
from debug_agent.adapters.go import GoAdapter
from debug_agent.adapters.python import PythonAdapter

__all__ = [
    "Adapter",
    "GoAdapter",
    "PythonAdapter",
    "detect_language",
    "find_free_port",
    "get_adapter",
    "list_adapters",
    "resolve_language",
    "wait_until_listening",
]

_REGISTRY: dict[str, type[Adapter]] = {
    PythonAdapter.name: PythonAdapter,
    GoAdapter.name: GoAdapter,
}


def list_adapters() -> list[str]:
    """All registered language names, sorted for stable output."""
    return sorted(_REGISTRY)


def get_adapter(name: str) -> Adapter:
    """Construct an adapter by language name. Raises ``ValueError`` if unknown."""
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown language {name!r}; known: {list_adapters()}")
    return cls()


def detect_language(script: Path | str | None) -> str | None:
    """Infer language from a script path's extension. Returns ``None`` if unknown."""
    if script is None:
        return None
    suffix = Path(script).suffix.lower()
    if not suffix:
        return None
    for name, cls in _REGISTRY.items():
        if suffix in cls.file_extensions:
            return name
    return None


def resolve_language(
    *,
    explicit: str | None,
    script: Path | str | None = None,
    default: str = "python",
) -> str:
    """Resolve the effective language: explicit ``--lang`` wins, else detect, else default.

    Raises ``ValueError`` if ``explicit`` names an unregistered language.
    """
    if explicit:
        if explicit not in _REGISTRY:
            raise ValueError(f"unknown --lang {explicit!r}; known: {list_adapters()}")
        return explicit
    detected = detect_language(script)
    if detected is not None:
        return detected
    return default
