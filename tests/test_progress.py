from __future__ import annotations

import io

import pytest

from playlist_builder.progress import ConsoleScanProgress, ScanProgress


class TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class BrokenStream(io.StringIO):
    def isatty(self) -> bool:
        return True

    def write(self, value: str) -> int:
        raise BrokenPipeError("closed")


class BrokenTTYProbe(io.StringIO):
    def isatty(self) -> bool:
        raise OSError("terminal unavailable")


def test_console_progress_rate_limit_and_summary() -> None:
    output = TTYBuffer()
    times = iter((1.0, 1.1, 1.3))
    reporter = ConsoleScanProgress(output, clock=lambda: next(times), max_updates_per_second=5)
    reporter(ScanProgress("file_processed", 1, 4, 1))
    reporter(ScanProgress("file_processed", 2, 4, 2))
    reporter(ScanProgress("file_processed", 3, 4, 3))
    reporter(ScanProgress("complete", 4, 4, 3, 1, 1, 2.25))
    rendered = output.getvalue()
    assert rendered.count("Procesando:") == 2
    assert "\x1b" not in rendered
    assert "Escaneo completado: 4/4 (100%)" in rendered


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_update_rate_must_be_finite_and_positive(value: float) -> None:
    with pytest.raises(ValueError, match="finito"):
        ConsoleScanProgress(io.StringIO(), max_updates_per_second=value)


def test_stream_failures_disable_progress_without_propagating() -> None:
    reporter = ConsoleScanProgress(BrokenStream())
    reporter(ScanProgress("discovery_started"))
    reporter(ScanProgress("complete", total=1, processed=1))


def test_isatty_and_clock_failures_do_not_propagate() -> None:
    reporter = ConsoleScanProgress(BrokenTTYProbe())
    reporter(ScanProgress("complete", total=1, processed=1))
    dynamic = ConsoleScanProgress(TTYBuffer(), clock=lambda: (_ for _ in ()).throw(RuntimeError()))
    dynamic(ScanProgress("file_processed", total=1, processed=1))
    dynamic(ScanProgress("complete", total=1, processed=1))
