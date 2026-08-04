from __future__ import annotations

import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol, TextIO

ProgressPhase = Literal["discovery_started", "discovery_complete", "file_processed", "complete"]


@dataclass(frozen=True, slots=True)
class ScanProgress:
    phase: ProgressPhase
    processed: int = 0
    total: int | None = None
    valid: int = 0
    cached: int = 0
    errors: int = 0
    elapsed_seconds: float = 0.0


class ProgressCallback(Protocol):
    def __call__(self, progress: ScanProgress) -> None: ...


class ConsoleScanProgress:
    """Rate-limited terminal renderer that never interrupts the scan."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_updates_per_second: float = 5.0,
    ) -> None:
        if not math.isfinite(max_updates_per_second) or max_updates_per_second <= 0:
            raise ValueError("max_updates_per_second debe ser finito y mayor que cero")
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock
        self.minimum_interval = 1 / max_updates_per_second
        try:
            self.dynamic = bool(self.stream.isatty())
        except Exception:
            self.dynamic = False
        self._last_update: float | None = None
        self._dynamic_width = 0
        self._disabled = False

    @staticmethod
    def _counters(progress: ScanProgress) -> str:
        total = "?" if progress.total is None else str(progress.total)
        percent = ""
        if progress.total is not None:
            value = 100 if progress.total == 0 else progress.processed * 100 / progress.total
            percent = f" ({value:.0f}%)"
        return (
            f"{progress.processed}/{total}{percent} · válidas: {progress.valid} · "
            f"caché: {progress.cached} · errores: {progress.errors}"
        )

    def __call__(self, progress: ScanProgress) -> None:
        if self._disabled:
            return
        try:
            self._render(progress)
        except Exception:
            self._disabled = True
            self.dynamic = False

    def _render(self, progress: ScanProgress) -> None:
        if progress.phase == "complete":
            if self.dynamic:
                self.stream.write("\r" + " " * self._dynamic_width + "\r")
            self.stream.write(
                f"Escaneo completado: {self._counters(progress)} · "
                f"{progress.elapsed_seconds:.1f} s\n"
            )
            self.stream.flush()
            return
        if not self.dynamic:
            return
        if progress.phase == "discovery_started":
            self.stream.write("Buscando archivos de audio…\n")
        elif progress.phase == "discovery_complete":
            self.stream.write(f"Encontrados {progress.total or 0} archivos de audio.\n")
        elif progress.phase == "file_processed":
            now = self.clock()
            is_last = progress.total is not None and progress.processed == progress.total
            if (
                not is_last
                and self._last_update is not None
                and now - self._last_update < self.minimum_interval
            ):
                return
            self._last_update = now
            line = f"Procesando: {self._counters(progress)}"
            self.stream.write(f"\r{line:<{self._dynamic_width}}")
            self._dynamic_width = max(self._dynamic_width, len(line))
        self.stream.flush()
