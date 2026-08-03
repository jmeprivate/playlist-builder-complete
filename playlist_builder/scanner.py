from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from .cache import CacheEntry, load_cache, write_cache
from .config import AUDIO_EXTENSIONS, CACHE_FILENAME
from .metadata import read_song
from .models import AuditIssue, AuditReport, Song

LOGGER = logging.getLogger(__name__)
MetadataReader = Callable[[Path, Path], Song]


def _is_inside(path: Path, parent: Path | None) -> bool:
    if parent is None:
        return False
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_stale_copy_stage(relative: Path) -> bool:
    return any(part.startswith(".playlist-copy-") for part in relative.parts)


def _error_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    try:
        return candidate.relative_to(root)
    except ValueError:
        return Path(candidate.name or ".")


def _discover_audio_files(
    root: Path, excluded: Path | None, report: AuditReport
) -> list[Path]:
    paths: list[Path] = []

    def record_walk_error(exc: OSError) -> None:
        problem = Path(exc.filename) if exc.filename else root
        report.issues.append(AuditIssue(_error_path(problem, root), error=f"OSError: {exc}"))
        LOGGER.warning("No se pudo recorrer %s: %s", problem, exc)

    for directory, dirnames, filenames in os.walk(root, topdown=True, onerror=record_walk_error):
        current = Path(directory)
        try:
            current_relative = current.relative_to(root)
        except ValueError as exc:
            report.issues.append(AuditIssue(Path(current.name), error=f"ValueError: {exc}"))
            dirnames[:] = []
            continue

        kept_directories: list[str] = []
        for dirname in sorted(dirnames, key=lambda value: (value.casefold(), value)):
            child = current / dirname
            relative = current_relative / dirname
            try:
                resolved = child.resolve()
            except (OSError, RuntimeError) as exc:
                report.issues.append(
                    AuditIssue(relative, error=f"{type(exc).__name__}: {exc}")
                )
                LOGGER.warning("No se pudo resolver %s: %s", child, exc)
                continue
            if _is_inside(resolved, excluded) or _is_stale_copy_stage(relative):
                continue
            kept_directories.append(dirname)
        dirnames[:] = kept_directories

        for filename in sorted(filenames, key=lambda value: (value.casefold(), value)):
            path = current / filename
            if path.suffix.casefold() not in AUDIO_EXTENSIONS:
                continue
            relative = current_relative / filename
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve()
            except (OSError, RuntimeError) as exc:
                report.total_audio_files += 1
                report.issues.append(
                    AuditIssue(relative, error=f"{type(exc).__name__}: {exc}")
                )
                LOGGER.warning("No se pudo inspeccionar %s: %s", path, exc)
                continue
            if _is_inside(resolved, excluded) or _is_stale_copy_stage(relative):
                continue
            paths.append(path)

    return paths


def scan_library(
    root: Path,
    *,
    rescan: bool = False,
    excluded_root: Path | None = None,
    metadata_reader: MetadataReader = read_song,
) -> tuple[list[Song], AuditReport]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"La raíz musical no existe o no es un directorio: {root}")
    excluded = excluded_root.expanduser().resolve() if excluded_root is not None else None
    cache_path = root / CACHE_FILENAME
    old_cache = {} if rescan else load_cache(cache_path, root)
    new_cache: dict[str, CacheEntry] = {}
    songs: list[Song] = []
    report = AuditReport()

    paths = _discover_audio_files(root, excluded, report)
    report.total_audio_files += len(paths)
    for path in paths:
        try:
            relative = path.relative_to(root)
            stat = path.stat()
        except (OSError, ValueError) as exc:
            report.issues.append(
                AuditIssue(_error_path(path, root), error=f"{type(exc).__name__}: {exc}")
            )
            LOGGER.warning("No se pudo inspeccionar %s: %s", path, exc)
            continue

        key = relative.as_posix()
        cached = old_cache.get(key)
        if cached and cached.size == stat.st_size and cached.mtime_ns == stat.st_mtime_ns:
            song, error = cached.song, cached.error
            LOGGER.debug("Caché válida: %s", relative)
        else:
            try:
                song = metadata_reader(path, root)
                error = None
                LOGGER.debug("Metadatos leídos: %s", relative)
            except Exception as exc:
                song = None
                error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("No se pudieron leer metadatos de %s: %s", relative, exc)
        new_cache[key] = CacheEntry(stat.st_size, stat.st_mtime_ns, song, error)
        if song is None:
            report.issues.append(AuditIssue(relative, error=error or "error desconocido"))
            continue
        songs.append(song)
        missing = tuple(
            name
            for name, absent in (
                ("Artist", not song.artist),
                ("Genre", not song.genres),
                ("Year", song.year is None),
            )
            if absent
        )
        if missing:
            report.issues.append(AuditIssue(relative, missing_tags=missing))

    write_cache(cache_path, new_cache)
    return songs, report
