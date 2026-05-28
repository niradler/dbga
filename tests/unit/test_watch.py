from __future__ import annotations

import sys
from pathlib import Path

from debug_agent.core.watch import WatchMatch, scan_file, scan_process


def test_scan_file_finds_pattern(tmp_path: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("info\nERROR boom\nwarn\nERROR fail\n")
    matches = list(scan_file(f, patterns=[r"ERROR (\w+)"]))
    assert len(matches) == 2
    assert isinstance(matches[0], WatchMatch)
    assert matches[0].line_number == 2
    assert matches[0].groups == ("boom",)
    assert matches[1].line_number == 4


def test_scan_process_collects_matches() -> None:
    matches = list(
        scan_process(
            [sys.executable, "-u", "-c", "print('a'); print('ERROR b'); print('c')"],
            patterns=[r"ERROR (\w+)"],
            timeout=5.0,
        )
    )
    assert len(matches) == 1
    assert matches[0].groups == ("b",)
