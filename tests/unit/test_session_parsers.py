from __future__ import annotations

from pathlib import Path

from debug_cli.commands.session import _parse_bp_with_condition, _parse_break_at


def test_break_at_file_line() -> None:
    parsed = _parse_break_at("app.py:42")
    assert parsed == (Path("app.py"), 42)


def test_break_at_rejects_bad_line() -> None:
    assert _parse_break_at("app.py:abc") is None
    assert _parse_break_at("app.py:0") is None
    assert _parse_break_at("app.py") is None


def test_break_at_keeps_drive_letter() -> None:
    parsed = _parse_break_at(r"C:\proj\app.py:42")
    assert parsed is not None
    file, line = parsed
    assert line == 42
    assert str(file).endswith("app.py")


def test_bp_with_condition_no_condition() -> None:
    parsed = _parse_bp_with_condition("app.py:42")
    assert parsed == (Path("app.py"), 42, None)


def test_bp_with_condition_with_condition() -> None:
    parsed = _parse_bp_with_condition("app.py:42:i == 100")
    assert parsed is not None
    file, line, cond = parsed
    assert file == Path("app.py")
    assert line == 42
    assert cond == "i == 100"


def test_bp_with_condition_drive_letter_and_condition() -> None:
    parsed = _parse_bp_with_condition(r"C:\proj\app.py:42:x is None")
    assert parsed is not None
    file, line, cond = parsed
    assert line == 42
    assert cond == "x is None"
    assert str(file).endswith("app.py")
