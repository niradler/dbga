from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from debug_cli.core.state import ensure_state_dir, read_json, state_dir, write_json

VALID_KINDS = frozenset({"log", "breakpoint", "trace", "custom"})


@dataclass
class Instrumentation:
    id: str
    file: str
    original_line: int
    kind: str
    code: str
    inserted_at: str


def _snapshot_name(file: Path) -> str:
    resolved = str(file.resolve())
    safe = resolved.replace("\\", "_").replace("/", "_").replace(":", "_")
    return f"{safe}.bak"


def _detect_indent(lines: list[str], at_line: int) -> str:
    idx = at_line - 1
    if 0 <= idx < len(lines):
        line = lines[idx]
        return line[: len(line) - len(line.lstrip())]
    return ""


def _registry_path(cwd: Path) -> Path:
    return state_dir(cwd) / "instrumentation.json"


def _snapshots_dir(cwd: Path) -> Path:
    return state_dir(cwd) / "snapshots"


def _load_registry(cwd: Path) -> dict[str, dict[str, object]]:
    raw = read_json(_registry_path(cwd), default={})
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, dict[str, object]], raw)


def _save_registry(cwd: Path, registry: dict[str, dict[str, object]]) -> None:
    write_json(_registry_path(cwd), registry)


def add_instrumentation(
    file: Path,
    *,
    line: int,
    code: str,
    kind: str,
    cwd: Path,
) -> str:
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind!r}; must be one of {sorted(VALID_KINDS)}")
    if line < 1:
        raise ValueError(f"line must be >= 1, got {line}")

    ensure_state_dir(cwd)

    text = file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    # Allow inserting at len(lines)+1 (i.e. appending a new last line).
    if line > len(lines) + 1:
        raise ValueError(f"line {line} is beyond end of file ({len(lines)} lines)")

    snapshot_path = _snapshots_dir(cwd) / _snapshot_name(file)
    if not snapshot_path.exists():
        snapshot_path.write_bytes(file.read_bytes())

    indent = _detect_indent(lines, line)
    insertion = f"{indent}{code}\n"
    lines.insert(line - 1, insertion)
    file.write_text("".join(lines), encoding="utf-8")

    inst_id = secrets.token_hex(4)
    instrumentation = Instrumentation(
        id=inst_id,
        file=str(file),
        original_line=line,
        kind=kind,
        code=code,
        inserted_at=datetime.now(timezone.utc).isoformat(),
    )
    registry = _load_registry(cwd)
    registry[inst_id] = asdict(instrumentation)
    _save_registry(cwd, registry)
    return inst_id


def list_instrumentations(*, cwd: Path) -> list[Instrumentation]:
    registry = _load_registry(cwd)
    return [
        Instrumentation(
            id=cast(str, entry["id"]),
            file=cast(str, entry["file"]),
            original_line=cast(int, entry["original_line"]),
            kind=cast(str, entry["kind"]),
            code=cast(str, entry["code"]),
            inserted_at=cast(str, entry["inserted_at"]),
        )
        for entry in registry.values()
    ]


def revert(inst_id: str | None, *, cwd: Path) -> list[str]:
    """Revert instrumentation(s) by restoring file snapshot(s).

    v1 is file-level: reverting any id wipes ALL instrumentations on that file.
    Passing inst_id=None reverts every tracked file and clears the registry.
    """
    registry = _load_registry(cwd)
    snapshots = _snapshots_dir(cwd)

    if inst_id is None:
        files_to_restore = {
            cast(str, entry["file"])
            for entry in registry.values()
            if isinstance(entry.get("file"), str)
        }
        restored = _restore_files(files_to_restore, snapshots)
        _save_registry(cwd, {})
        return restored

    if inst_id not in registry:
        raise KeyError(f"instrumentation id not found: {inst_id}")

    target_file = str(registry[inst_id]["file"])
    restored = _restore_files({target_file}, snapshots)
    # File-level revert: drop all entries pointing at this file.
    new_registry = {k: v for k, v in registry.items() if v.get("file") != target_file}
    _save_registry(cwd, new_registry)
    return restored


def _restore_files(files: set[str], snapshots: Path) -> list[str]:
    restored: list[str] = []
    for f in sorted(files):
        path = Path(f)
        snap = snapshots / _snapshot_name(path)
        if snap.exists():
            path.write_bytes(snap.read_bytes())
            snap.unlink()
        restored.append(f)
    return restored
