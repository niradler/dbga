from __future__ import annotations

from pathlib import Path

from debug_cli.core.instrumentation import (
    Instrumentation,
    add_instrumentation,
    list_instrumentations,
    revert,
)


def test_add_inserts_and_records(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def f(x):\n    return x + 1\n")
    inst_id = add_instrumentation(
        target, line=2, code="print('debug', x)", kind="log", cwd=tmp_path
    )
    assert target.read_text() == "def f(x):\n    print('debug', x)\n    return x + 1\n"
    registry = list_instrumentations(cwd=tmp_path)
    assert len(registry) == 1
    assert isinstance(registry[0], Instrumentation)
    assert registry[0].id == inst_id


def test_revert_by_id_restores_file(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    original = "def f(x):\n    return x + 1\n"
    target.write_text(original)
    inst_id = add_instrumentation(target, line=2, code="print('x', x)", kind="log", cwd=tmp_path)
    reverted = revert(inst_id, cwd=tmp_path)
    assert reverted == [str(target)]
    assert target.read_text() == original
    assert list_instrumentations(cwd=tmp_path) == []


def test_revert_all(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    b = tmp_path / "b.py"
    b.write_text("y = 2\n")
    add_instrumentation(a, line=1, code="print('a')", kind="log", cwd=tmp_path)
    add_instrumentation(b, line=1, code="print('b')", kind="log", cwd=tmp_path)
    reverted = revert(None, cwd=tmp_path)
    assert set(reverted) == {str(a), str(b)}
    assert a.read_text() == "x = 1\n"
    assert b.read_text() == "y = 2\n"


def test_indentation_preserved(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def f(x):\n        return x + 1\n")  # 8-space indent
    add_instrumentation(target, line=2, code="pass", kind="log", cwd=tmp_path)
    lines = target.read_text().splitlines()
    assert lines[1] == "        pass"
    assert lines[2] == "        return x + 1"


def test_invalid_kind_raises(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("x = 1\n")
    try:
        add_instrumentation(target, line=1, code="pass", kind="bogus", cwd=tmp_path)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_snapshot_reused_across_adds(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    original = "x = 1\ny = 2\n"
    target.write_text(original)
    add_instrumentation(target, line=1, code="print('a')", kind="log", cwd=tmp_path)
    # Second add must reuse the original snapshot (not re-snapshot the modified file).
    add_instrumentation(target, line=1, code="print('b')", kind="log", cwd=tmp_path)
    # Revert via --all should restore original.
    revert(None, cwd=tmp_path)
    assert target.read_text() == original
