from __future__ import annotations

from pathlib import Path

from debug_cli.core.tracebacks import ParsedTraceback, attach_source, parse_traceback

FIXTURES = Path(__file__).parent.parent / "fixtures" / "tracebacks"


def test_parse_standard_traceback() -> None:
    text = (FIXTURES / "standard.txt").read_text()
    parsed = parse_traceback(text)
    assert isinstance(parsed, ParsedTraceback)
    assert parsed.error_type == "ZeroDivisionError"
    assert parsed.message == "division by zero"
    assert len(parsed.frames) == 2
    assert parsed.frames[0].file == "src/app.py"
    assert parsed.frames[0].line == 42
    assert parsed.frames[1].func == "transform"


def test_parse_chained_traceback() -> None:
    text = (FIXTURES / "chained.txt").read_text()
    parsed = parse_traceback(text)
    assert parsed.error_type == "RuntimeError"
    assert parsed.message == "failed to process"
    assert len(parsed.chained) == 1
    assert parsed.chained[0].error_type == "ValueError"


def test_parse_syntax_error() -> None:
    text = (FIXTURES / "syntax_error.txt").read_text()
    parsed = parse_traceback(text)
    assert parsed.error_type == "SyntaxError"
    assert parsed.message == "invalid syntax"
    assert len(parsed.frames) == 1
    assert parsed.frames[0].file == "src/bad.py"
    assert parsed.frames[0].line == 3
    assert parsed.frames[0].func == "<module>"


def test_parse_pytest_short() -> None:
    text = (FIXTURES / "pytest_short.txt").read_text()
    parsed = parse_traceback(text)
    assert parsed.error_type == "ZeroDivisionError"
    assert parsed.message == "division by zero"
    assert len(parsed.frames) == 2
    assert parsed.frames[0].file == "tests/test_foo.py"
    assert parsed.frames[0].line == 12
    assert parsed.frames[0].func == "test_bar"


def test_deepest_user_frame_skips_site_packages() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "src/app.py", line 5, in main\n'
        "    do_stuff()\n"
        '  File "/usr/lib/python3.10/site-packages/lib/x.py", line 99, in helper\n'
        "    raise RuntimeError\n"
        "RuntimeError: boom\n"
    )
    parsed = parse_traceback(text)
    assert parsed.deepest_user_frame is not None
    assert parsed.deepest_user_frame.file == "src/app.py"


def test_deepest_user_frame_skips_windows_lib() -> None:
    text = (
        "Traceback (most recent call last):\n"
        '  File "src/app.py", line 5, in main\n'
        "    do_stuff()\n"
        '  File "C:\\Python310\\Lib\\threading.py", line 99, in helper\n'
        "    raise RuntimeError\n"
        "RuntimeError: boom\n"
    )
    parsed = parse_traceback(text)
    assert parsed.deepest_user_frame is not None
    assert parsed.deepest_user_frame.file == "src/app.py"


def test_attach_source_fills_context(tmp_path: Path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n")
    parsed = parse_traceback(
        f"Traceback (most recent call last):\n"
        f'  File "{target}", line 3, in <module>\n'
        f"    c = 3\n"
        f"ValueError: x\n"
    )
    attach_source(parsed, context_lines=1)
    assert parsed.frames[0].code_context == ["b = 2", "c = 3", "d = 4"]


def test_attach_source_swallows_missing_files() -> None:
    parsed = parse_traceback(
        "Traceback (most recent call last):\n"
        '  File "definitely_not_a_real_file_xyz.py", line 3, in <module>\n'
        "    c = 3\n"
        "ValueError: x\n"
    )
    attach_source(parsed)
    assert parsed.frames[0].code_context == []
