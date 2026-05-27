from __future__ import annotations

from pathlib import Path

from debug_cli.core.watch import WatchMatch, scan_file


def test_scan_file_finds_pattern(tmp_path: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("info\nERROR boom\nwarn\nERROR fail\n")
    matches = list(scan_file(f, patterns=[r"ERROR (\w+)"]))
    assert len(matches) == 2
    assert isinstance(matches[0], WatchMatch)
    assert matches[0].line_number == 2
    assert matches[0].groups == ("boom",)
    assert matches[1].line_number == 4
