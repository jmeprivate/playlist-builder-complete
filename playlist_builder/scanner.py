from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from .cache import (
    CacheEntry,
    CacheHealth,
    CatalogCache,
    load_catalog_cache,
    utc_now,
    write_catalog_cache,
)
from .config import COPY_ROOT_MARKER, Settings, load_config
from .metadata import read_song
from .models import AuditIssue, AuditReport, Song
from .progress import ProgressCallback, ScanProgress

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
    root: Path,
    excluded: Path | None,
    extensions: frozenset[str],
    report: AuditReport,
) -> tuple[list[Path], int]:
    paths: list[Path] = []
    file_errors = 0

    def record_walk_error(exc: OSError) -> None:
        problem = Path(exc.filename) if exc.filename else root
        report.issues.append(
            AuditIssue(_error_path(problem, root), error=f"OSError: {exc}", is_directory=True)
        )
        LOGGER.warning("No se pudo recorrer %s: %s", problem, exc)

    for directory, dirnames, filenames in os.walk(root, topdown=True, onerror=record_walk_error):
        current = Path(directory)
        try:
            current_relative = current.relative_to(root)
        except ValueError as exc:
            report.issues.append(
                AuditIssue(Path(current.name), error=f"ValueError: {exc}", is_directory=True)
            )
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
                    AuditIssue(relative, error=f"{type(exc).__name__}: {exc}", is_directory=True)
                )
                LOGGER.warning("No se pudo resolver %s: %s", child, exc)
                continue
            if (child / COPY_ROOT_MARKER).is_file():
                LOGGER.info(
                    "Se omite %s: contiene el marcador %s de una exportación previa; "
                    "elimine ese archivo para volver a escanearla",
                    child,
                    COPY_ROOT_MARKER,
                )
                continue
            if _is_inside(resolved, excluded) or _is_stale_copy_stage(relative):
                continue
            kept_directories.append(dirname)
        dirnames[:] = kept_directories

        for filename in sorted(filenames, key=lambda value: (value.casefold(), value)):
            path = current / filename
            if path.suffix.casefold() not in extensions:
                continue
            relative = current_relative / filename
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve()
            except (OSError, RuntimeError) as exc:
                file_errors += 1
                report.issues.append(AuditIssue(relative, error=f"{type(exc).__name__}: {exc}"))
                LOGGER.warning("No se pudo inspeccionar %s: %s", path, exc)
                continue
            if _is_inside(resolved, excluded) or _is_stale_copy_stage(relative):
                continue
            paths.append(path)

    return paths, file_errors


def scan_library(
    root: Path,
    *,
    rescan: bool = False,
    excluded_root: Path | None = None,
    metadata_reader: MetadataReader | None = None,
    settings: Settings | None = None,
    progress: ProgressCallback | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[Song], AuditReport]:
    started_at = clock()
    settings = settings or load_config()

    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"La raíz musical no existe o no es un directorio: {root}")
    excluded = excluded_root.expanduser().resolve() if excluded_root is not None else None
    cache_path = root / settings.cache_filename
    metadata_signature = "year=unbounded-v1"
    loaded = CatalogCache() if rescan else load_catalog_cache(cache_path, root, metadata_signature)
    old_cache = loaded.files
    started = utc_now()
    incomplete = CacheHealth(
        started,
        None,
        False,
        loaded.health.last_read_at,
        dict(loaded.health.errors),
    )
    write_catalog_cache(
        cache_path,
        CatalogCache(dict(old_cache), incomplete),
        metadata_signature,
    )

    new_cache: dict[str, CacheEntry] = {}
    songs: list[Song] = []
    report = AuditReport()

    if progress is not None:
        progress(ScanProgress(phase="discovery_started"))
    paths, discovery_file_errors = _discover_audio_files(
        root, excluded, settings.audio_extensions, report
    )
    report.total_audio_files = len(paths) + discovery_file_errors
    if progress is not None:
        progress(ScanProgress(phase="discovery_complete", total=report.total_audio_files))

    cached_count = 0
    error_count = discovery_file_errors
    for processed_count, path in enumerate(paths, start=discovery_file_errors + 1):
        try:
            relative = path.relative_to(root)
            stat = path.stat()
        except (OSError, ValueError) as exc:
            relative = _error_path(path, root)
            report.issues.append(AuditIssue(relative, error=f"{type(exc).__name__}: {exc}"))
            error_count += 1
            if progress is not None:
                progress(
                    ScanProgress(
                        "file_processed",
                        processed_count,
                        report.total_audio_files,
                        len(songs),
                        cached_count,
                        error_count,
                        clock() - started_at,
                    )
                )
            continue

        key = relative.as_posix()
        cached = old_cache.get(key)
        unchanged = (
            cached is not None
            and cached.size == stat.st_size
            and cached.mtime_ns == stat.st_mtime_ns
        )
        if cached is not None and cached.error is not None:
            song, error, error_at = cached.song, cached.error, cached.error_at
            cached_count += 1
            LOGGER.debug("Error conservado en caché hasta --rescan: %s", relative)
        elif cached is not None and unchanged:
            song, error, error_at = cached.song, cached.error, cached.error_at
            cached_count += 1
            LOGGER.debug("Caché válida: %s", relative)
        else:
            try:
                song = read_song(path, root) if metadata_reader is None else metadata_reader(path, root)
                error = error_at = None
                LOGGER.debug("Metadatos leídos: %s", relative)
            except Exception as exc:
                song = None
                error = f"{type(exc).__name__}: {exc}"
                error_at = utc_now()
                LOGGER.warning("No se pudieron leer metadatos de %s: %s", relative, exc)

        new_cache[key] = CacheEntry(stat.st_size, stat.st_mtime_ns, song, error, error_at)
        if song is None:
            report.issues.append(AuditIssue(relative, error=error or "error desconocido"))
            error_count += 1
        else:
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
            informational = ("AlbumArtist",) if not song.album_artists else ()
            if missing or informational:
                report.issues.append(
                    AuditIssue(relative, missing_tags=missing, informational_tags=informational)
                )

        if progress is not None:
            progress(
                ScanProgress(
                    "file_processed",
                    processed_count,
                    report.total_audio_files,
                    len(songs),
                    cached_count,
                    error_count,
                    clock() - started_at,
                )
            )

    health_errors = {
        issue.relative_path.as_posix(): issue.error
        for issue in report.issues
        if issue.error is not None
    }
    complete = CacheHealth(started, utc_now(), True, loaded.health.last_read_at, health_errors)
    write_catalog_cache(
        cache_path,
        CatalogCache(new_cache, complete),
        metadata_signature,
    )
    if progress is not None:
        progress(
            ScanProgress(
                "complete",
                report.total_audio_files,
                report.total_audio_files,
                len(songs),
                cached_count,
                error_count,
                clock() - started_at,
            )
        )
    return songs, report
