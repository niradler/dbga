from __future__ import annotations

from pathlib import Path

from debug_cli.core.tracebacks import ParsedTraceback, parse_traceback

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
